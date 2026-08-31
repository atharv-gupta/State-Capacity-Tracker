# Spec: Add Governor Press-Release Sources

## Goal
Add all-50-states governors' office press releases as a new input to the existing
pipeline, tagged as a distinct `source_type = "gov-release"`. These are
primary-source government activity (highest provenance) and catch actions the
news-only feeds miss — e.g. NY's "Express NY" red-tape release at
`https://www.governor.ny.gov/news/...`, which the current pipeline did not catch.

This is an **additive** change. Do not break the existing RSS path or downstream stages.

## Existing architecture (read first, preserve it)
- `pipeline.py` ingests via `sources.all_feeds()`, which yields specs shaped
  `(state, name, url, source_type)`. RSS is parsed by `feedparser` in
  `parse_feed` / `fetch_feed`, with WordPress-style `?paged=N` pagination.
- `extract_article(spec, entry)` normalizes each feed entry into a dict with keys:
  `state, publisher, source_type, title, published (iso str), pub_date (date), url, summary`.
- Everything after ingest (date gate, keyword pre-screen, classify, Airtable write)
  is **source-agnostic** — it only needs that article dict.
- `SOURCE_TYPES = ["statenewsroom", "newspaper", "trade-press"]`.

## What to build

### 1. Two ingestion paths for governors
- **RSS governors (preferred):** add them as ordinary entries in `sources.py` with
  `source_type="gov-release"`. No new fetch code — they flow through the existing
  `feedparser` path. Use this wherever a governor site exposes a working feed.
- **Non-RSS governors:** a **config-driven** HTML scraper. Add
  `sources.gov_html_sources()` returning a list of configs, each:
  `{state, name, list_url, base_url, item_selector, title_selector, link_selector,
  date_selector, date_format (optional), summary_selector (optional)}`.
  One generic scraper reads the config — no bespoke per-state code. Allow an optional
  `custom_parse` callable as an escape hatch for sites that genuinely need it.

### 2. Generic HTML fetcher
- `fetch_gov_html(config, min_date) -> list[article dict]`, output matching
  `extract_article`'s shape **exactly** (same keys), with `source_type="gov-release"`.
- Use `requests` + `beautifulsoup4`. Set a descriptive `User-Agent`. Parse the listing
  page; per item pull title, absolute link (resolve relative against `base_url`), date
  (robust parse via `python-dateutil`), and summary if a selector is given.
- Keep only items with `pub_date >= min_date`. If a date can't be parsed, **skip the
  item** rather than guessing.
- Per-source `try/except` so one broken governor never kills the run (mirror
  `parse_feed`). Print a one-line warning on failure. Add a small politeness delay
  between page fetches.

### 3. Wire into `main()`
- After the existing RSS fetch loop fills `articles`, run the HTML governors
  (concurrently, but with fewer workers) and `extend` `articles` with their dicts.
- Respect the existing `--states` filter — only run governors for requested states.
- Everything downstream stays unchanged.

### 4. `source_type` plumbing
- Add `"gov-release"` to `SOURCE_TYPES` and to the `source_type` singleSelect choices
  in `REQUIRED_FIELDS` so `ensure_table` includes it. (Writes already pass
  `typecast=True`, which will also create the option on the fly, but list it explicitly.)

### 5. Guardrails on endpoints — IMPORTANT
- **Do not hallucinate governor URLs or RSS paths.** For any RSS feed you add, fetch it
  first and confirm it parses with `feedparser` and returns recent entries; only then add it.
- Seed with a **verified starter set** — whatever you can confirm this session (aim ~8–12
  states). For every remaining state, leave a clearly-marked `TODO` config stub in
  `sources.py` (one per state, `list_url` blank to fill) so the registry is complete and
  obviously incomplete.
- Add a helper `tools/discover_gov_feeds.py`: given a state + governor newsroom URL, probe common
  feed paths (`/news/feed`, `/feed`, `/rss`, `/news/rss`, `?format=rss`, etc.), validate any
  hit parses, and print per state either a confirmed RSS URL or "no RSS — needs HTML config."
  This is how the registry gets filled to 50 safely, without guessing.

### 6. Dependencies
- Add `requests`, `beautifulsoup4`, `python-dateutil`. Import `bs4`/`requests` lazily so a
  pure-RSS run still works if they're absent.

## Out of scope (note only — separate task)
- `dedupe.py`: when a gov-release and news articles cluster into one event, prefer the
  gov-release URL as the canonical `source_url` and treat news coverage as corroboration.
  Flag as a follow-up; **do not** implement here.

## Acceptance
- `python -m tracker.state.pipeline NY --days 30 --dry-run` should surface the Express NY / red-tape
  release as a passed `gov-release` event — proving the new path catches what news-only missed.
- `python -m tracker.state.pipeline --dry-run` (all sources) runs without regressing the existing feeds.
- Run `tools/discover_gov_feeds.py` for the seed states and print its output so we can fill the registry.
