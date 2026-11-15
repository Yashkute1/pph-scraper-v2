# Amazon: prices and stock from the Creators API, scraper kept for finding products

Status: short design, waiting for approval. Size: a small change (one module, one hook, one workflow edit, tests).

## Intent and why
The Amazon scraper marks every offer in stock (4,613 of 4,613 on 13 Nov) because a search card shows a price whether or
not the item can be bought. A trial of the Creators API on 5 real products found one out of stock, one a preorder
(February 2027) and one with no offer at all. The owner asked to use the API together with the scraper for a better
result: the API makes price and stock true, the scraper keeps finding products.

## Goals
- Every Amazon offer the scraper finds gets its price and stock from the API when the API answers.
- If the API cannot answer (not eligible, rate limit, network, credentials), the Amazon run behaves exactly as today.
- No credential ever appears in a log, artifact or the public `scrapes` branch.

## Non-goals
- Replacing the scraper's discovery of new products (search returns 10 items per request through the API).
- Any other store; any change to the site; titles, images and categories still come from the scraper.
- A separate, more frequent price refresh job.
- Reading the Creators API terms on how long price data may be kept: the owner checks that (see open items).

## Anti-goals (a failure even if it technically works)
- An API problem stops Amazon prices updating at all.
- API calls past the account's limit (1 request a second, 8,640 a day for a new account) so the account is throttled.
- Prices shown as fresher than they are.

## Constraints
- GitHub machines have no database access (the Hostinger server writes it), so this works on the scraped list only.
- A call checks up to 10 ASINs. About 4,600 products is about 460 calls, a few minutes, four runs a day: about 1,850
  calls a day, a fifth of the daily limit, leaving room for retries and manual checks.
- Access depends on the Associates account's qualifying sales, so it can stop at any time. Fallback is required.

## Approaches
A. **Enrich inside the Amazon scrape job (picked).** After the scraper has normalised its offers and before they are saved
   or published, ask the API about those ASINs and correct price and stock. One place, no new job, the published file and
   the server's write path stay as they are.
B. A separate API refresh job between scrapes. Fresher, but needs a second publisher to the `scrapes` branch and a merge on
   the server: more moving parts for prices that already refresh every six hours.
C. API for known products plus a once-a-day scrape for discovery. Needs the known ASIN list kept somewhere GitHub can read
   it, and halves how often new listings appear. More machinery for little gain.

## Design (A)
- New `pph/amazon_api.py`: `enrich(offers, session)` returns the offers with API price and stock where known, plus a
  one-line summary. The existing probe (`tools/amazon_api_probe.py`) already proves the token and `getItems` calls; the
  module reuses its token host rule (version 3.2 = api.amazon.co.uk), marketplace `www.amazon.in`, and resources
  `itemInfo.title`, `offersV2.listings.price`, `offersV2.listings.availability`.
- Hook in `pph/run.py` `scrape()`: for store `amazon`, when the four Amazon settings are present, call `enrich` on the
  normalised offers before write, save or dry-run reporting. Any exception inside it is caught and means "keep the
  scraper's values".
- Rules per product, from the buy-box listing (else the first listing):
  - IN_STOCK: in stock, price from the API.
  - IN_STOCK_SCARCE (few left) counts as IN_STOCK.
  - OUT_OF_STOCK, or no listing: not in stock, scraper's price kept as the last seen price.
  - PREORDER: not in stock (it cannot be bought today). Builder call, easy to change.
  - Any other type (for example AVAILABLE_DATE, seen once with a normal price): keep the scraper's stock flag, take the API
    price, and count the type in the run note so the rule can be set from data. Builder call.
- Calls: batches of 10, at most one call a second, token reused until a few minutes before it expires. A 429 waits and
  retries twice, then stops using the API for the rest of the run. An authorisation or "not eligible" answer stops it at
  once. The run note says what happened, for example "api: 4,590 of 4,613 checked, 41 out of stock, 3 preorder".
- Workflow: the Amazon matrix entry (scrape and its retry) gets `AMAZON_CREATORS_*` and `AMAZON_PARTNER_TAG` in its
  environment; other stores get none. Nothing prints them; GitHub masks the secrets and the code logs counts only.
- Tests: fake API answers cover each rule, batching, 429 retry, not-eligible fallback, a network error, an unknown type,
  and that no credential text can reach the note. A live check runs the Amazon API check workflow and a dry-run scrape.

## Left to the builder
Exact retry waits, how the token is cached in memory, the log wording, and the PREORDER and unknown-type calls above.

## Open items for the owner
- Read the Creators API terms on storing prices and keeping price history. This design stores what the site stores today.
- Keep qualifying sales coming: if the API stops answering, the scraper values return and stock flags go back to "in stock".
