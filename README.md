# pph-scraper-v2

Price scraper for [PC Part Hunt](https://pcparthunt.com). It reads PC component
listings from nine Indian stores, cleans and groups them, and writes one row per
part to the site's database. It runs on GitHub-hosted runners every six hours.

Stores: elitehubs, vishalperipherals, pcstudio, primeabgb, vedantcomputers,
mdcomputers, theitdepot, flipkart, amazon.

## Develop

```
pip install -r requirements-dev.txt
pytest -q
python -m pph.run scrape pcstudio --dry-run --max-pages 1
```

Tests never use the network or a database.

## Design

See `docs/superpowers/specs/` and `docs/superpowers/plans/`.
