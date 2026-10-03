# PC Part Hunt scraper v2 — design

Date: 2026-10-04. Status: awaiting owner review.

## Purpose

Keep pcparthunt.com's prices current for nine Indian stores, for free, with no
machine of the owner's involved. The Raspberry Pi and PC that fed most of the
catalogue are gone; 71% of the database (Amazon, Flipkart) has not been updated
since 10 Aug 2026.

Success means:
- All nine stores are refreshed daily from GitHub-hosted runners.
- A bad run can never wipe or falsely mark a store out of stock.
- The site can read one ready-made row per part, with a real "last updated" time.
- The repo is public and contains no credentials, in code or in history.

## Decisions made by the owner

- Use Scrapling (Python). Free infrastructure only. No paid proxy, no own servers.
- Amazon and Flipkart are included.
- New public repo with clean history; the old private scraper is retired.
- Product images are captured.

## Evidence

`docs/probe/` holds two reachability probes run from a GitHub runner on
2026-10-04. All nine stores were readable:

| Store | Adapter | Fetcher |
|---|---|---|
| elitehubs | `shopify_feed` (`/products.json`) | HTTP |
| vishalperipherals | `shopify_feed` | HTTP |
| pcstudio | `woo_store_api` (`/wp-json/wc/store/v1/products`) | HTTP |
| primeabgb | `html_listing` | HTTP |
| vedantcomputers | `html_listing` | HTTP |
| mdcomputers | `html_listing` | HTTP |
| theitdepot | `html_listing` | HTTP |
| flipkart | `html_listing` | HTTP |
| amazon | `html_listing` | Stealth browser |

Unproven: behaviour at thousands of requests a day (Amazon and Flipkart may
start serving captchas), and product-page parsing for Vedant and TheITDepot.
The design therefore treats every store as able to fail on any day.

## Architecture

```
stores.py        per-store config: adapter, fetcher, start URLs, selectors, limits
adapters/        shopify_feed.py, woo_store_api.py, html_listing.py
fetch.py         thin wrapper over Scrapling: per-host delay, retries, block detection
normalize.py     price parsing, brand, category, model key   (ported from Node)
group.py         group_id + product roll-up                  (ported from Node)
store_db.py      MongoDB writes, sanity gate, stale handling
run.py           CLI: `run.py scrape <store>`, `run.py rollup`, `--dry-run`
tests/           unit tests + saved HTML/JSON fixtures per store
```

Each unit has one job. Adapters return raw dicts and know nothing about the
database. `normalize` and `group` are pure functions. Only `store_db` talks to
MongoDB.

### Adapters

An adapter yields raw offers: `title, price, mrp, url, image, in_stock, sku?`.

- `shopify_feed`: pages `/products.json?limit=250&page=N` and, because the feed
  stops at about 5,000 products, also walks each collection's feed.
- `woo_store_api`: pages the store API, 100 per page.
- `html_listing`: fetches category or search pages, reads every product card
  with per-store CSS selectors, follows pagination to a per-store cap. It opens
  a product page only when a card lacks price or image.

Amazon and Flipkart use search and category URLs for the site's PC categories
only, paged deep. Off-topic results are dropped by the category rules.

### Fetching

- HTTP: `Fetcher.get(impersonate="chrome")`. Browser: `StealthyFetcher.fetch`.
- Per-host delay of 1–2s (Amazon 3–5s), three retries with backoff.
- A response is "blocked" when status is 403/429/503 or the body is a
  Cloudflare or captcha page. Three blocked pages in a row stop that store's
  run and mark it failed.

### Normalising and grouping

Ported from `pph-scraper/lib/normalize.js`, `lib/aggregate.js` and the newer
rules in the API's `pphRegroup.js` (junk-title filter, non-PC filter,
per-category price ceilings, accessory detection, build detection). The
existing JS test cases are ported first and must pass before any rule changes.

New: brands map to one canonical spelling (`ASUS`, `Zotac` → `ZOTAC`).

### Data model (MongoDB `pph_site`, new collections)

`offers` — one per store listing, `_id` = hash of store + URL:
`store, url, title, price, mrp, in_stock, image, brand, category, model_key,
group_id, first_seen, last_seen, missed_runs, history[{d, p}]`
(`history` keeps one point per day, last 90 days).

`products_v2` — one per `group_id`, rebuilt by the roll-up step:
`group_id, title, brand, category, image, best_price, best_store, best_url,
mrp, any_stock, store_count, stores[], offers[{store, price, in_stock, url}],
low_90d, updated_at, specs`.
Indexes: `category+any_stock+store_count`, `category+best_price`, `brand`,
text on `title`.

`scrape_runs` — one per store per run:
`store, started, finished, status(ok|partial|blocked|failed), fetched, written,
previous_count, note`.

The old `products` collection is not touched. The current site keeps working
on it until the rebuilt site switches to `products_v2`.

Storage: the free tier allows 512 MB. Budget is checked in the roll-up step and
reported; history is trimmed first if space runs short.

### Run safety

- Sanity gate: a store's results are written only if the run was not blocked
  and returned at least 60% of that store's previous count. Otherwise nothing
  for that store changes and the run is recorded as `partial` or `blocked`.
- `missed_runs` increases only after a run that passed the gate. At 3 the offer
  is marked out of stock; after 14 days unseen it is deleted.
- Roll-up runs after all store jobs, whatever their result, from current
  `offers`.

### Schedule (GitHub Actions)

- `scrape.yml`: daily 22:00 UTC (03:30 IST) and manual. A matrix job per store,
  running in parallel, each with its own timeout; then one `rollup` job.
- `ci.yml`: tests on every push and pull request.

### Security

- Secrets (`MONGO_URI`) only in GitHub Secrets. The scraper never prints
  connection strings; errors are logged by type.
- A dedicated database user for the scraper, read/write on `pph_site` only.
  The password is rotated when this scraper goes live.
- Workflows: `permissions: contents: read`, no `pull_request_target`, actions
  pinned to commit SHAs, secrets unavailable to fork pull requests.
  The one exception is a `report` job that commits a run summary to a `status`
  branch; it has write access to the repo and receives no secrets.
- Secret scanning and push protection enabled. Dependabot for Python packages.
- Store affiliate codes are not in this repo; they stay on the site side.

### Reporting

Each run writes a table to the Actions summary and to `scrape_runs`. A failed
or blocked store fails its matrix job, so GitHub emails the owner, without
stopping the other stores.

## Testing

- Unit tests for normalise and group (ported cases plus brand canonicalisation).
- Adapter tests against saved fixtures for every store; no network in CI.
- `--dry-run` scrapes and prints counts without writing.
- First live runs go store by store with `--dry-run`, then with writes.

## Out of scope

- Background-removed image cutouts (the 24,000 existing ones stay usable).
- Amazon PA-API and Flipkart affiliate API.
- The site rebuild and DPDP compliance, which get their own spec.

## Cut-over

1. The old scraper's schedule was disabled on 2026-10-04 at the owner's request.
2. This scraper writes only the new collections; the database password is
   rotated when its secret is set.
3. After a week of clean runs, the rebuilt site reads `products_v2`.
