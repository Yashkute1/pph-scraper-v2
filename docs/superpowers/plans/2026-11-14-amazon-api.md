# Amazon Creators API Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amazon offers get their price and stock from the Creators API after the scraper finds them, and fall back to scraped values whenever the API cannot answer.

**Architecture:** One new stdlib-only module, `pph/amazon_api.py`, with pure rules (what an API item means for an offer), a rate-limited client, and `enrich`. `pph.run.scrape()` calls it for store `amazon` between collecting offers and saving or writing them. The Amazon scrape steps in `scrape.yml` receive the four Amazon settings; no other store does.

**Tech Stack:** Python (`urllib`, `json`, `re`; no new packages), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-14-amazon-api-design.md`

## Global Constraints
- Runs on Python 3.11 and 3.12: the Hostinger server imports `pph.run` on 3.11. No 3.12-only syntax; import `pph.amazon_api` lazily inside the hook.
- Standard library only. API token host for credential version 3.2 is `api.amazon.co.uk`, endpoint `https://creatorsapi.amazon/catalog/v1/getItems`, marketplace `www.amazon.in`, resources `itemInfo.title`, `offersV2.listings.price`, `offersV2.listings.availability` (same as `tools/amazon_api_probe.py`, which stays unchanged).
- At most 10 ASINs per call and at most 1 call a second (account limit: 1 request a second, 8,640 a day).
- Credentials never appear in the run note, logs, exceptions or artifacts; only counts do. The run note is cut to 255 characters by the database writer.
- An API problem never fails or blocks the Amazon scrape: the offers go on as scraped.
- Rules: IN_STOCK gets the API price; OUT_OF_STOCK or no listing is not in stock with the scraped price kept; PREORDER is not in stock; any other type keeps the scraped stock flag, takes the API price, and is counted in the note.
- Commit as `Yash Kute <65953242+Yashkute1@users.noreply.github.com>`, no AI trailers.

## Review Focus
1. An item with `offersV2` missing, `listings` empty, or an `errors` entry for its ASIN: treated as "no listing", never a crash (Task 1, Task 3).
2. IN_STOCK with a missing, zero or negative price: the scraped price stays, never 0 (Task 1).
3. The API returns fewer items than asked: those offers keep scraped values and are counted (Task 3).
4. The same ASIN twice in the scraped list: asked once, every offer with it corrected (Task 3).
5. A 429 or "not eligible" part-way through 460 calls: offers already corrected keep API values, the rest keep scraped values, and the note says where it stopped (Task 2, Task 3).

---

### Task 1: Rules for one API item

**Files:**
- Create: `pph/amazon_api.py`
- Test: `tests/test_amazon_api.py`

**Interfaces:**
- Produces: `asin_of(url: str) -> str | None`; `classify(item: dict | None) -> tuple[str, float | None]` returning kind in `"in_stock" | "out_of_stock" | "preorder" | "other" | "missing"` and the buy-box price (the listing with `isBuyBoxWinner` true, else the first listing; `None` when absent or not above 0); `apply(offer: dict, kind: str, price: float | None) -> dict` returning a corrected copy.

- [ ] **Step 1: Write failing tests** in `tests/test_amazon_api.py`, with a helper `item(type_, amount=None, buybox=True)` building `{"asin": "B0TEST0001", "offersV2": {"listings": [{"availability": {"type": type_}, "isBuyBoxWinner": buybox, "price": {"money": {"amount": amount}}}]}}`:
  - `test_asin_of`: `asin_of("https://www.amazon.in/dp/B0CJJKF2Q2")` is `"B0CJJKF2Q2"`; `asin_of("https://x.test/p/1")` is `None`.
  - `test_classify_kinds`: `("IN_STOCK", 1499.0)` -> `("in_stock", 1499.0)`; `OUT_OF_STOCK` -> `"out_of_stock"`; `PREORDER` -> `"preorder"`; `AVAILABLE_DATE` -> `"other"`.
  - `test_missing_item_or_listing`: `classify(None)`, `classify({"asin": "B0X"})`, and an item with `"listings": []` are all `("missing", None)`.
  - `test_buy_box_listing_wins`: two listings, the second with `isBuyBoxWinner` true, price comes from the second.
  - `test_a_bad_price_is_never_used`: IN_STOCK with amount `None`, `0` and `-5` returns price `None`.
  - `test_apply_rules`: base offer `{"price": 1000, "mrp": 1200, "in_stock": True}`: in_stock with 1499.0 -> price 1499, mrp 1499 (mrp never below price), stock True; out_of_stock and missing and preorder -> stock False, price 1000; other with 1100.0 -> price 1100, stock unchanged (try a base with `in_stock` False); in_stock with price `None` -> price 1000 kept, stock True. The input offer is not modified.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_amazon_api.py -q`. Expected: FAIL, no module `pph.amazon_api`.
- [ ] **Step 3: Implement** the three functions in `pph/amazon_api.py`. `asin_of` matches `/dp/([A-Z0-9]{10})`; prices go through `round()`.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `pph/amazon_api.py tests/test_amazon_api.py` as "Amazon API: what an item means for an offer".

### Task 2: Client with rate limit and stop rules

**Files:**
- Modify: `pph/amazon_api.py`
- Test: `tests/test_amazon_api.py`

**Interfaces:**
- Consumes: `classify` from Task 1 is not used here.
- Produces: `class ApiStop(Exception)`; `credentials(env: Mapping[str, str]) -> dict | None` (keys `id`, `secret`, `version`, `tag`; `None` if any of `AMAZON_CREATORS_CREDENTIAL_ID`, `AMAZON_CREATORS_CREDENTIAL_SECRET`, `AMAZON_CREATORS_CREDENTIAL_VERSION`, `AMAZON_PARTNER_TAG` is missing or blank; version accepts a leading `v`); `class AmazonApi` with `__init__(self, creds: dict, post=_post, sleep=time.sleep, clock=time.monotonic)` and `get_items(self, asins: list[str]) -> dict[str, dict]` mapping ASIN to the raw item, asking for at most 10. `post(url: str, body: dict, headers: dict) -> tuple[int, str]` is the injectable HTTP call.

- [ ] **Step 1: Write failing tests** with a fake `post` recording calls and a fake clock/sleep:
  - `test_credentials_need_all_four`: complete env gives a dict with `version == "3.2"` for `"v3.2"`; each missing or blank key gives `None`.
  - `test_get_items_returns_items_by_asin`: the fake answers the token call (200, `{"access_token": "T", "expires_in": 3600}`) then getItems; the result maps ASIN to item; the getItems body has `itemIdType "ASIN"`, `marketplace "www.amazon.in"`, the partner tag, the three resources; the call carries `Authorization: Bearer T`.
  - `test_token_is_reused_and_refreshed`: two `get_items` calls make one token call; after the clock passes `expires_in - 120` the next call makes a second one.
  - `test_calls_are_at_least_one_second_apart`: three calls with a fake clock that does not advance on its own make `sleep` totals of at least 2 seconds.
  - `test_more_than_ten_asins_is_refused`: 11 ASINs raise `ValueError`.
  - `test_429_waits_and_retries_twice_then_stops`: answers 429, 429, 429: `sleep` waits recorded, then `ApiStop`; answers 429 then 200: returns normally.
  - `test_stop_answers`: HTTP 401 or 403, an `AssociateNotEligible` body, a token call answered 400, each raise `ApiStop` at once with no retry.
  - `test_errors_never_carry_credentials_or_bodies`: `str(ApiStop)` for a 403 whose body contains the secret and the id contains neither.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_amazon_api.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** `ApiStop`, `credentials`, `_post` (urllib, JSON, 30 s timeout, returns `(status, text)` also for HTTP errors) and `AmazonApi`. Token host from `{"3.1": "api.amazon.com", "3.2": "api.amazon.co.uk", "3.3": "api.amazon.co.jp"}`; an unknown version raises `ApiStop`. Retry waits 5 s then 20 s on 429. `ApiStop` messages carry only the HTTP status and the API's error code word, never the body.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** as "Amazon API: client with rate limit, token reuse and stop rules".

### Task 3: Enrich and hook into the scrape

**Files:**
- Modify: `pph/amazon_api.py`, `pph/run.py` (in `scrape()`, after the `try/except` that fills `offers` and before `seconds = int(clock() - t0)`), `.github/workflows/scrape.yml` (`env:` of "Scrape ${{ matrix.store }}" and "Scrape ${{ matrix.store }} again")
- Test: `tests/test_amazon_api.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: `asin_of`, `classify`, `apply` (Task 1); `AmazonApi`, `ApiStop`, `credentials` (Task 2).
- Produces: `enrich(offers: list[dict], api) -> tuple[list[dict], str]` (corrected copies plus a note such as `api: 4590 of 4613 checked, 41 out of stock, 3 preorder, 2 other (AVAILABLE_DATE:2)`); `enrich_from_env(offers, env=os.environ, **kw) -> tuple[list[dict], str]` which returns `(offers, "")` without credentials and, on any exception, `(offers, "api: unavailable (<ExceptionName>)")`.

- [ ] **Step 1: Write failing tests** in `tests/test_amazon_api.py` with a fake `api` object whose `get_items(asins)` returns canned items and records batches:
  - `test_enrich_corrects_and_counts`: three offers (in stock, out of stock, missing from the answer) return price, stock and note counts as above; the missing one keeps scraped values and is counted as "not returned".
  - `test_same_asin_twice_is_asked_once`: two offers with one ASIN produce one ASIN in the batches and both are corrected.
  - `test_batches_of_ten`: 25 offers produce batches of 10, 10, 5.
  - `test_stop_midway_keeps_earlier_corrections`: the fake raises `ApiStop` on the second batch: the first 10 offers corrected, the rest unchanged, note says `api: stopped after 10 of 25`.
  - `test_item_without_offers_is_missing_not_a_crash`: an item `{"asin": ..}` only, and one with an `errors`-style shape, count as out of stock/missing.
  - `test_enrich_from_env`: no credentials gives `(offers, "")` and no HTTP call; an exception from the client gives the "unavailable" note with only the exception name, offers unchanged; a note never contains the secret string.
  In `tests/test_run.py`:
  - `test_amazon_scrape_uses_the_api_and_still_works_without_it`: with the existing fake-adapter helpers, store `amazon` and `monkeypatch.setattr` on `pph.amazon_api.enrich_from_env`: the saved or written offers carry corrected values and the run note contains the api note; when it raises, the run is unchanged (`status "ok"`). Another store never calls it.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_amazon_api.py tests/test_run.py -q`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** `enrich` and `enrich_from_env` in `pph/amazon_api.py`, and the hook in `pph/run.py`: for `store == "amazon"` and not an adapter failure, `from . import amazon_api` inside the hook, `offers, api_note = amazon_api.enrich_from_env(offers)`, then append `api_note` to `note` (joined by `"; "`) when not empty. Edit `scrape.yml`: in both Scrape steps' `env:` add the four settings as `${{ matrix.store == 'amazon' && secrets.AMAZON_CREATORS_CREDENTIAL_ID || '' }}` (same pattern for `_SECRET`; and `vars.AMAZON_CREATORS_CREDENTIAL_VERSION`, `vars.AMAZON_PARTNER_TAG`, which the API check workflow already reads from variables).
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q` and `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/scrape.yml'))"`. Expected: all pass, no output from the second command. Also run `tests/test_amazon_api.py tests/test_run.py` with the 3.11 environment.
- [ ] **Step 5: Commit** as "Amazon: price and stock from the Creators API when it answers".

### Task 4: Live check

**Files:** none changed unless the check finds a problem.

- [ ] **Step 1:** Push to `main`, wait for CI to pass.
- [ ] **Step 2:** Push a branch `dryrun/amazon-api` (a dry run, two pages a search, no writes); in the Amazon job's summary the note shows `api: N of M checked, ...` with counts. Delete the branch afterwards.
- [ ] **Step 3:** After the next real scrape and the server's write, check on pcparthunt.com that some Amazon offers show "Out of stock" and that the log of the Amazon job has no credential text. Report the counts (in stock, out of stock, preorder, other types) to the owner.
