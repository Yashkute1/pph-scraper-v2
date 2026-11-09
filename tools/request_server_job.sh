#!/bin/sh
# Ask the Hostinger server to run a job from the list in tools/hostinger_sync.py, and wait for its result.
#   GITHUB_TOKEN=... sh tools/request_server_job.sh rollup
# The request is one commit on the `server-jobs` branch. The server's cron job looks every 10 minutes and publishes the
# result at /api/export/job.json, so this waits up to 40 minutes and passes or fails with the job.
set -eu
job=$1
id="${GITHUB_RUN_ID}${GITHUB_RUN_ATTEMPT:-1}"

dir=$(mktemp -d)
printf '{"job": "%s", "id": "%s"}\n' "$job" "$id" > "$dir/job.json"
git -C "$dir" init -q -b server-jobs
git -C "$dir" config user.name "pph-bot"
git -C "$dir" config user.email "pph-bot@users.noreply.github.com"
git -C "$dir" add -A
git -C "$dir" commit -qm "job: $job ($id)"
git -C "$dir" push -q --force "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" HEAD:server-jobs
echo "requested $job as $id"

i=0
while [ "$i" -lt 80 ]; do
  sleep 30
  i=$((i + 1))
  body=$(curl -fsS --max-time 30 https://pcparthunt.com/api/export/job.json 2>/dev/null || true)
  case "$body" in
    *"\"id\": \"$id\""*)
      echo "$body"
      case "$body" in *'"status": "ok"'*) exit 0 ;; *) exit 1 ;; esac ;;
  esac
done
echo "::error::the server did not report on this job within 40 minutes"
exit 1
