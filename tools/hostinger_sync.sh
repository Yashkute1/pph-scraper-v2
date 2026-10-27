#!/bin/sh
# Cron entry on the Hostinger server: keep the code current, then write new scrapes into MySQL (tools/hostinger_sync.py).
# One cron job installs and runs it (the command must stay under 255 characters):
#   /bin/sh -c 'd=$HOME/pph/code; [ -d $d ] || git clone -q --depth 1 https://github.com/Yashkute1/pph-scraper-v2 $d; sh $d/tools/hostinger_sync.sh'
# Everything lives in ~/pph: code/ (this repository, shallow), venv/ (Python 3.11 with the two database packages),
# state/ (which scrapes commit was written last) and logs/.

main() {
  base="$HOME/pph"; code="$base/code"; venv="$base/venv"; state="$base/state"
  mkdir -p "$state" "$base/logs"
  log="$base/logs/sync-$(date -u +%Y-%m).log"

  # One at a time: a roll-up can outlast the cron interval. A lock older than three hours is from a killed run.
  if ! mkdir "$state/lock" 2>/dev/null; then
    [ -n "$(find "$state/lock" -maxdepth 0 -mmin +180 2>/dev/null)" ] || return 0
    rmdir "$state/lock" && mkdir "$state/lock" || return 0
  fi
  trap 'rmdir "$state/lock" 2>/dev/null' EXIT

  # The scrapes branch appears with the first published scrape; until then only main is fetched.
  git -C "$code" fetch -q --depth 1 origin +refs/heads/main:refs/remotes/origin/main \
      +refs/heads/scrapes:refs/remotes/origin/scrapes 2>/dev/null ||
    git -C "$code" fetch -q --depth 1 origin +refs/heads/main:refs/remotes/origin/main 2>>"$log"
  git -C "$code" reset -q --hard origin/main

  want=$(cksum < "$code/requirements-server.txt")
  if [ ! -x "$venv/bin/python" ] || [ "$(cat "$venv/.req" 2>/dev/null)" != "$want" ]; then
    /opt/alt/python311/bin/python3 -m venv "$venv" &&
      "$venv/bin/pip" install -q --disable-pip-version-check -r "$code/requirements-server.txt" >>"$log" 2>&1 &&
      echo "$want" > "$venv/.req"
  fi

  cd "$code" && "$venv/bin/python" -m tools.hostinger_sync "$code" "$state" 2>&1 | tee -a "$log"
}

# On one line, so the shell has read all of it before `git reset` replaces this file.
main "$@"; exit $?
