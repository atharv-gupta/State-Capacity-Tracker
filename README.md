# State Capacity Tracker

A weekly, queryable feed of what state governments are actually doing, classified by which of Recoding America's four state-capacity competencies it advances or undermines: **civil-service** (workforce — hiring, classification, pay, performance, separation), **procedure** (the government's own process/compliance burden), **digital** (how the state builds, buys, and oversees its own technology and data), and **incentives** (the learning/feedback loop — outcome-tied funding, oversight, evaluation). Most real government actions fit none of the four — that's expected and recorded as `none`.

The pipeline ingests ~170 state-government news feeds, keeps only items that represent real government activity touching those capacities, de-duplicates them into distinct *events*, classifies each against Recoding America's rubric, stores everything in Airtable, and surfaces a filterable map view on the web.

## How it works

```
[Ingest]            [Gate]                   [Store raw]      [Dedupe + classify]   [Surface]
171 RSS feeds  -->  keyword pre-screen  -->  'Raw Events' --> cluster same      --> 'Events' table
last N days         + 2 LLM gates            one row per     event, classify        one row per event
                    (provenance, capacity)   article         vs. rubric (Sonnet)    + web map view
```

1. **`pipeline.py`** — fetches every feed in `sources.py` (paging back through WordPress feeds until past the lookback window, since many feeds retain <7 days), keeps items from the last N days, pre-screens with competency keywords (cheap, before any LLM call), then gates each survivor with Claude Haiku:
   - **Gate 1 (provenance):** is the underlying activity an action by a *state-level* government actor in their official capacity? Bills, vetoes, EOs, rulemaking, appointments, reorgs, procurement, budgets, program launches, audits. Federal-only, city-only, opinion, campaign coverage, and private lawsuits fail.
   - **Gate 2 (competency):** does it touch one of the four capacities — civil-service / procedure / digital / incentives? (A coarse filter; the final competencies are decided per-event in step 2.)
   - Survivors land in the **`Raw Events`** Airtable table, one row per article, tagged with state, candidate pillar(s), activity type, and actor type.
2. **`dedupe.py`** — clusters the window's raw rows (one government action shows up across many outlets) with Claude Sonnet, then classifies **every** event against the rubric in **`rubric.md`** (sent as a cached system prompt): zero, one, or more **competencies** (an event can span two — e.g. oversight of a failing IT system is both `digital` and `incentives`; matching none is the common case), a **1–3 relevance** score for how central an example it is (direction-agnostic — undermining a capacity counts as much as advancing it), and a set of descriptive **topic tags**. It then rebuilds that window of the **`Events`** table: one row per event, all source URLs/outlets merged. Rows outside the window are never touched, so the table accumulates history week over week. Use `--all` to reclassify every raw row and `--clean-table NAME` to build into a side table (e.g. for review before swapping it in).
3. **`web/`** — Next.js app: US map shaded by event count, filters for time window (week / month / all), competency, topic tag, activity type, and government actor type, with an event list beneath; each event shows its competencies, a relevance dot rating, and clickable topic-tag chips. Reads Airtable server-side via `/api/events` (the token never reaches the browser).

## Congressional tracker

A parallel pipeline covering the seven committees that govern how the *federal* government
runs itself — Senate HSGAC, Senate Rules, Senate Appropriations, House Oversight, House
Administration, House Rules, House Appropriations — plus both whips and CBO. Same four
competencies, re-pointed at the federal government by
**`congress_rubric_adaptation.md`**, which is prepended to the shared `rubric.md`. The state
rubric is untouched.

Two independent paths, because hearings and bills need no clustering — one API record *is*
one hearing or one bill, with a stable ID:

```
[Press path]   28 sources (HSGAC WP API + 14 RSS + 11 HTML)
                 --> keyword pre-screen --> Haiku gate --> 'Congress Raw'
                 --> congress_dedupe.py (cluster + Sonnet rubric) --> 'Congress Events'

[API path]     Congress.gov  --> committee-meeting  --> 'Congress Hearings'
                             --> committee/*/bills  --> 'Congress Bills'
```

- **`congress_sources.py`** — the registry. HSGAC and Padilla expose WordPress REST APIs
  (typed endpoints, full article bodies, server-side `?after=` filtering); 14 sources have
  working RSS; 11 need HTML scraping. No JS rendering anywhere, so no headless browser.
  `python congress_fetch.py --days 21` probes every source and prints what each returned.
- **`congress_api_sync.py`** — hearings and bills. `--crosscheck` compares HSGAC's own CMS
  against Congress.gov on hearing date; as of the last run the API covered everything the
  CMS had, plus one hearing it didn't.
- Both clean tables **upsert** rather than delete-and-rewrite, and `review_status` /
  `reviewer_notes` are preserved on update — so a reviewer's annotations survive nightly runs.
- `Congress Raw` carries an `ingested_at` timestamp and `congress_dedupe.py` windows on it,
  rather than on the model-supplied action date (see Known gaps).

```bash
.venv/bin/python congress_pipeline.py --days 21 --dry-run   # per-source funnel, no writes
.venv/bin/python congress_pipeline.py --days 21
.venv/bin/python congress_dedupe.py   --days 21
.venv/bin/python congress_api_sync.py --days 21
```

The dry-run funnel prints fetched → in-window → pre-screened → passed per source. That table
is how you tell "this committee was quiet" from "this scraper broke" — several member offices
legitimately go weeks without posting, especially during recess.

## Federal executive-branch tracker

A third pipeline, covering what the **executive branch** does to itself: OMB memoranda, OPM
and GSA instruments, executive orders, the Federal Register, and the federal trade press that
covers all of it. Same four competencies, re-pointed by
**`federal_rubric_adaptation.md`**, which is prepended to the shared `rubric.md` exactly as
the congressional adaptation is. Neither the state rubric nor the congressional adaptation is
touched.

This is a separate tab from Congress rather than a section of it, because the two answer
different questions. Congress is primary-source and committee-shaped — who has jurisdiction,
what did they hold a hearing on. This is instrument-shaped — what did an agency actually
issue, and what does it change. Hill coverage that lands here carries a `congress` branch chip
instead of being filed twice.

```
[news]              8 outlets (4 WordPress APIs + 4 RSS)
                      --> keyword pre-screen (+ anchor for broad beats)
                      --> Haiku instrument gate --> 'Federal Raw'

[executive-action]  4 agency listings (OPM, OMB news, OMB memoranda, GSA)
                      --> Haiku instrument gate --> 'Federal Raw'

[oversight]         GAO reports feed
                      --> Haiku instrument gate --> 'Federal Raw'

[rulemaking]        26 Federal Register API queries
                      --> Haiku instrument gate --> 'Federal Raw'

                          all four --> federal_dedupe.py
                          (cluster by agency + Sonnet rubric) --> 'Federal Events'
```

### The four lanes, and why the lane belongs to the source

The lane is assigned by the SOURCE, never by the model: a FedScoop story about an OMB memo is
news *about* an executive action, and conflating the two would let trade-press coverage
masquerade as a primary-source instrument. When a cluster spans lanes the highest-provenance
member wins — `LANE_RANK = {executive-action: 4, rulemaking: 3, oversight: 2, news: 1}`. So a
Federal Register rule plus a Federal News Network story files under `rulemaking`; that same
rule plus OPM's own release files under `executive-action`; a GAO report plus three trade
write-ups files under `oversight`. An instrument always outranks the coverage of it, and it
also outranks a finding about it: if OPM issues guidance in response to a GAO report, the
event is the guidance.

`oversight` is GAO, moved here from the Congress tab on 2026-08-20. Its own lane rather than
`executive-action` for two reasons: GAO is a legislative-branch auditor, so filing it as an
executive action mislabels it; and at ~24 reports per 21 days it outweighs everything else on
the tab, so it has to be collapsible. Agency inspectors general are *not* routed here — an IG
audit reported by FedScoop arrives through the news lane, which is where it belongs, because
the lane records how directly you are hearing it.

The web view offers one link per kind out of each expanded event — the instrument and one
press write-up of it — split on whether the source host is a `.gov`. A cluster holding a
Federal Register rule and a Federal News Network story shows both, rather than whichever URL
sorted first.

### The instrument test

The gate that matters here is not provenance but **instrument**. Executive-branch press
offices produce a great deal of language and comparatively few actions, and the language is
written to be quoted. An item enters only when a concrete thing can be named: a numbered OMB
memorandum or circular, agency guidance, a directive or delegation, a proposed or final rule,
an executive order, a workforce action actually taken (RIF, hiring authority, reclassification,
bargaining order), a procurement action, a system launched or shut off, a reorganization, a
report with findings, or a court order compelling an agency. ICYMI items, interviews, op-eds,
statements responding to statements, and announcements of intent to be more efficient all
fail. Everything that passes is then **restated neutrally** — the promotional and partisan
adjectives are stripped, and each row carries the primary document so the framing can be
checked against the instrument.

Reported and draft-stage actions are **kept and labelled**, not dropped: a trade outlet
describing a draft memo before it is signed is often the earliest real signal. Every row
records `verification` as `official`, `reported`, or `draft-leaked`.

### Where the pre-screen applies, and where it deliberately doesn't

- **news** — pre-screened. Sources flagged `broad` in the registry (The Hill, ~100 posts a
  day across every beat) must *also* hit a machinery **anchor** — a named institution or
  instrument — because the capacity vocabulary alone matches half of general political
  coverage on words like "oversight", "accountability" and "AI". In the first 21-day window
  that took The Hill from 1,706 posts to 13 candidates and 5 events, while FedScoop kept 20
  of 45.
- **executive-action** — not pre-screened. About ten items a window, and the point of the
  lane is that a bland agency headline can hide a governmentwide instrument.
- **rulemaking** — not pre-screened. The Federal Register queries *are* the pre-screen.

### How the Federal Register is scoped

The full Register runs ~1,637 documents per 21 days (1,285 notices, 220 rules, 115 proposed
rules, 17 presidential documents), nearly all of it ordinary agency regulatory business, plus
~525 routine Paperwork Reduction Act collection renewals. Pulling all of it would cost roughly
ten times as much for a handful more events, so `federal_sources.py` queries the API three
ways: complete coverage of the seven agencies whose subject matter *is* the machinery of
government (OPM, OMB, GSA, MSPB, FLRA, OGE, NARA), every presidential document, and an
18-phrase capacity-vocabulary sweep across all agencies to catch mission-agency actions that
scoping by agency would miss. That is 212 documents fetched, 18 kept, in the first window.

```bash
.venv/bin/python federal_sources.py                          # print the registry
.venv/bin/python federal_fetch.py --days 21                  # reachability probe
.venv/bin/python federal_pipeline.py --days 21 --dry-run     # per-source funnel, no writes
.venv/bin/python federal_pipeline.py --days 21
.venv/bin/python federal_dedupe.py   --days 21
```

Both federal steps run **daily** in the workflow, like the congressional ones. Two of the
three lanes are perishable: Government Executive and Nextgov hold about seven days of feed and
The Hill about two, so a missed day is a permanent hole.

### Reviewer package — workbooks and walkthrough documents

Two generators, both writing into `review/` (gitignored):

**`export_review.py`** writes one .xlsx per tracker: the deduped layer *and* the raw layer,
filterable, with a verdict dropdown, a Read me sheet stating what the reviewer is deciding,
and rows that matched no competency shaded rather than hidden (the reviewer is checking for
false negatives too). The two layers are both there on purpose — the raw sheet carries the
cheap gate's `pillars` guess, the events sheet carries the authoritative `competency` and
`relevance`, and the disagreement between them is where the second model overruled the first.

**`export_docs.py`** writes one walkthrough per tracker: a plain-language description of how
an item becomes a row (sources → keyword pre-screen → gate → clustering → classification),
then appendices carrying every prompt, keyword list and enum **verbatim**. The appendices are
read out of the live modules at build time rather than retyped, so a prompt edit can never
leave the document describing a pipeline that no longer exists. Markdown always; `.docx` too
when pandoc is installed, because reviewers need to comment.

```bash
.venv/bin/python export_review.py                     # both trackers, last 21 days -> review/
.venv/bin/python export_review.py --tracker federal --days 7
.venv/bin/python export_review.py --all --relevant-only --out ~/Desktop
.venv/bin/python export_docs.py                       # md + docx walkthroughs -> review/
.venv/bin/python export_docs.py --format md
```

The export is deliberately one-way. Airtable's `review_status` / `reviewer_notes` are the
durable record (the upsert path preserves them through every nightly run), so a verdict typed
into the workbook has to be typed back there to survive; round-tripping would mean two sources
of truth for the same field.

### Known gaps & gotchas (federal)

- **The four GovExec-family outlets have no API** — Government Executive, Nextgov/FCW, Route
  Fifty and Washington Technology all run the same platform, and their feeds ignore
  pagination, so each holds ~25 items (~7 days). A backfill longer than a week cannot reach
  back through them; only the daily run keeps them whole.
- **The Hill is the most expensive source and the least productive.** In the first three-week
  window it fetched 1,706 posts to reach 13 candidates and 4 events, and every in-window event
  it touched was already covered by FedScoop or Federal News Network — its two solo items were
  both dated outside a 30-day view. Kept for now because federal-capacity coverage there is
  episodic rather than absent, but it is the first source to cut if cost matters.
- **OMB's newsroom is near-dead** — 10 items reaching back into 2025. The memoranda listing is
  the real signal and is scraped separately. The memos are PDFs, so they are classified on
  title and listing text; adding a PDF dependency for a few documents a year isn't worth it.
- **whitehouse.gov blocks `wp-json`** (403), so OMB is scraped rather than API'd.
- **GAO's feed holds exactly 25 items** — about three weeks at its cadence — so the daily run
  is what keeps the oversight lane whole, and a backfill longer than three weeks cannot reach
  back through it. `gao.gov/rss/press.xml` is deliberately unused: it has published nothing
  since 2026-06-04 and its items announce the same reports.
- **There is still no dedupe between the federal and congressional trackers.** Moving GAO
  removed the case that was actually producing duplicates, but a committee press release about
  an executive-branch action can still land on both tabs. Nothing in either pipeline prevents
  it.
- **Items are dated by the action, not by publication.** A story published this week about
  guidance issued in May is dated May and falls outside a 30-day view. `federal_dedupe.py`
  windows on `ingested_at`, so nothing is lost from the table — but the default UI window can
  hide it. Storing the publication date alongside the action date is the fix; it is not built
  yet because it would be blank for every backfilled row.
- **Clustering groups by agency**, using the alphabetically-first *subject* agency (GAO,
  `governmentwide`, `courts` and `other` are treated as reporters, not subjects). Sorting is
  what makes the key order-independent: two outlets covering one GAO report on FEMA returned
  `["gao","fema"]` and `["fema","gao"]` and were surviving as duplicate events until the key
  was sorted. Rows whose agency lists don't overlap at all still can't cluster together.
- **Federal Register term queries have low individual yield** — most of the 18 phrases
  contributed zero events in the first window, and the ones that did (Treasury's Do Not Pay
  designation, NIST's NVD modernization RFI, deregulatory agenda notices) came from a handful.
  They cost ~180 Haiku calls per backfill and are the first place to trim if cost matters.
- **The `instrument_type` vocabulary is press-shaped, not legislative.** A news story about a
  bill introduction can come back as `regulation-proposed`; the `branch` field is the reliable
  signal for congressional items.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env_example .env   # fill in the values
```

`.env` needs `ANTHROPIC_API_KEY`, `AIRTABLE_TOKEN` (scopes: data.records read/write, schema.bases read/write), and `AIRTABLE_BASE_ID`. `CONGRESS_API_KEY` (free, from [api.congress.gov](https://api.congress.gov)) is needed only for the congressional hearings and bills sync; without it that one script skips cleanly. Tables and fields are created automatically if missing.

Run manually:

```bash
.venv/bin/python pipeline.py --days 7    # ingest the past week into Raw Events
.venv/bin/python dedupe.py --days 7      # cluster that window into Events
```

Useful flags: `pipeline.py CO KS --dry-run --limit 20` (specific states, no writes, capped LLM calls) for tuning sessions; `--days 31` for backfills (bounded by feed retention — most feeds can't reach back more than a few weeks even with pagination).

Web view:

```bash
cd web && npm install
cp ../.env  .env.local   # or create .env.local with AIRTABLE_TOKEN + AIRTABLE_BASE_ID
npm run dev              # http://localhost:3000
```

## Weekly email digest

`digest.py` composes one email covering both halves of the tracker and sends it via Resend,
after the dedupe steps have rebuilt the clean tables:

```
STATE     four competency sections, then Governors '26
FEDERAL   the week's calendar, then Congress by competency,
          then agencies and the executive branch by competency
```

Five tables feed it — `Events`, `Candidate Events`, `Congress Events`, `Congress Hearings`,
`Federal Events` — and a table that doesn't exist yet is skipped rather than fatal, so a half
that has never run degrades to a "nothing notable" line instead of killing the send.

Three structural decisions worth knowing before editing:

- **Every section renders through one item shape** (`item()`), so adding a section is a loader
  plus a selection rule. The previous version had a renderer per section and they had drifted.
- **State shows all four competencies even when empty; federal omits empty ones.** The state
  rhythm is the tracker's spine and readers learn it. Federal has two branch groups times four
  competencies, and eight "nothing notable" lines is a wall of nothing.
- **Federal deduplicates across competency sections; state doesn't.** On the federal side
  `incentives` is nearly co-extensive with "a watchdog published something", so without this
  the Incentives subsection restates most of Digital and Civil service — 22 slots for 15
  events the first week. Federal items print under the first competency they match and carry
  the rest on the meta line ("also incentives").

```bash
.venv/bin/python digest.py --days 7 --dry-run              # per-section counts, no send
.venv/bin/python digest.py --days 7 --html-out /tmp/d.html # preview file, no send
.venv/bin/python digest.py --days 7                        # compose and send
```

`--html-out` deliberately does **not** send — writing a preview is a look-before-you-send
action, and the earlier behaviour of sending anyway mailed a real digest during development.
Pass `--send` alongside it to do both.

## Automation

`.github/workflows/weekly.yml` runs the ingest every day at 13:00 UTC (~7am MT) — daily because 90+ feeds retain less than a week of items (see Known gaps) — and additionally runs dedupe on Mondays. It can be triggered manually from the Actions tab (with an opt-in checkbox to also dedupe). To activate, add the repo secrets on GitHub: **Settings → Secrets and variables → Actions → New repository secret** for `ANTHROPIC_API_KEY`, `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID`, and `CONGRESS_API_KEY`.

**All three congressional steps run daily**, including the classify step — unlike the state pipeline, whose dedupe is Mondays only. Upcoming hearings are perishable: a Monday-only classify would surface a Wednesday hearing notice after the hearing had already happened.

## Deploying the web view (Vercel)

1. [vercel.com](https://vercel.com) → Add New → Project → import this GitHub repo.
2. Set **Root Directory** to `web/`.
3. Add environment variables `AIRTABLE_TOKEN` and `AIRTABLE_BASE_ID`.
4. Deploy. Every push to `main` redeploys automatically.

## Sources

Three layers, each doing a different job (see `SPEC.md` §4). The registry lives in `sources.py` and is a **living artifact** — feeds were RSS-verified on 2026-06-09; prune dead ones and add new outlets as found. The competency keyword lists at the top of `pipeline.py` (civil-service, procedure, digital, incentives) are the other living artifact: misses come from missing keywords, not missing outlets.

The web view's **Sources & methodology** tab renders a snapshot of this registry. After editing `sources.py`, regenerate it with `python sources.py --json > web/app/methodology/sources.json`.

<!-- SOURCES:BEGIN (generated from sources.py) -->

**171 feeds total** — 39 States Newsroom + 131 newspapers/outlets + 1 trade press.

### Layer 1 — Spine: States Newsroom (39 states)

Nonprofit statehouse newsrooms, one per state, pulled at `https://<domain>/feed/localFeed`.

| State | Outlet |
|---|---|
| AK | [alaskabeacon.com](https://alaskabeacon.com) |
| AL | [alabamareflector.com](https://alabamareflector.com) |
| AR | [arkansasadvocate.com](https://arkansasadvocate.com) |
| AZ | [azmirror.com](https://azmirror.com) |
| CO | [coloradonewsline.com](https://coloradonewsline.com) |
| FL | [floridaphoenix.com](https://floridaphoenix.com) |
| GA | [georgiarecorder.com](https://georgiarecorder.com) |
| IA | [iowacapitaldispatch.com](https://iowacapitaldispatch.com) |
| ID | [idahocapitalsun.com](https://idahocapitalsun.com) |
| IN | [indianacapitalchronicle.com](https://indianacapitalchronicle.com) |
| KS | [kansasreflector.com](https://kansasreflector.com) |
| KY | [kentuckylantern.com](https://kentuckylantern.com) |
| LA | [lailluminator.com](https://lailluminator.com) |
| MD | [marylandmatters.org](https://marylandmatters.org) |
| ME | [mainemorningstar.com](https://mainemorningstar.com) |
| MI | [michiganadvance.com](https://michiganadvance.com) |
| MN | [minnesotareformer.com](https://minnesotareformer.com) |
| MO | [missouriindependent.com](https://missouriindependent.com) |
| MT | [dailymontanan.com](https://dailymontanan.com) |
| NC | [ncnewsline.com](https://ncnewsline.com) |
| ND | [northdakotamonitor.com](https://northdakotamonitor.com) |
| NE | [nebraskaexaminer.com](https://nebraskaexaminer.com) |
| NH | [newhampshirebulletin.com](https://newhampshirebulletin.com) |
| NJ | [newjerseymonitor.com](https://newjerseymonitor.com) |
| NM | [sourcenm.com](https://sourcenm.com) |
| NV | [nevadacurrent.com](https://nevadacurrent.com) |
| OH | [ohiocapitaljournal.com](https://ohiocapitaljournal.com) |
| OK | [oklahomavoice.com](https://oklahomavoice.com) |
| OR | [oregoncapitalchronicle.com](https://oregoncapitalchronicle.com) |
| PA | [penncapital-star.com](https://penncapital-star.com) |
| RI | [rhodeislandcurrent.com](https://rhodeislandcurrent.com) |
| SC | [scdailygazette.com](https://scdailygazette.com) |
| SD | [southdakotasearchlight.com](https://southdakotasearchlight.com) |
| TN | [tennesseelookout.com](https://tennesseelookout.com) |
| UT | [utahnewsdispatch.com](https://utahnewsdispatch.com) |
| VA | [virginiamercury.com](https://virginiamercury.com) |
| WA | [washingtonstatestandard.com](https://washingtonstatestandard.com) |
| WI | [wisconsinexaminer.com](https://wisconsinexaminer.com) |
| WV | [westvirginiawatch.com](https://westvirginiawatch.com) |

### Layer 2 — Breadth: state newspapers & outlets (RSS-verified 2026-06-09)

Complementary coverage per state; the only layer covering the 11 states with no States Newsroom outlet (CA, CT, DE, HI, IL, MA, MS, NY, TX, VT, WY).

| State | Outlets |
|---|---|
| AK | [Anchorage Daily News](https://www.adn.com/arc/outboundfeeds/rss/?outputType=xml), [Juneau Empire](https://www.juneauempire.com/feed/) |
| AL | [Alabama Daily News](https://aldailynews.com/feed/), [Alabama Political Reporter](https://www.alreporter.com/feed/), [AL.com](https://www.al.com/arc/outboundfeeds/rss/?outputType=xml) |
| AR | [Arkansas Times](https://arktimes.com/feed), [Talk Business & Politics](https://talkbusiness.net/feed/) |
| AZ | [Arizona Capitol Times](https://azcapitoltimes.com/feed/), [KJZZ](https://www.kjzz.org/politics.rss) |
| CA | [CalMatters](https://calmatters.org/feed/), [Capitol Weekly](https://capitolweekly.net/feed/), [LA Times Politics](https://www.latimes.com/politics/rss2.0.xml) |
| CO | [The Colorado Sun](https://coloradosun.com/feed/), [Colorado Politics](https://www.coloradopolitics.com/feed/) |
| CT | [CT Mirror](https://ctmirror.org/feed/), [CT News Junkie](https://ctnewsjunkie.com/feed/) |
| DE | [Spotlight Delaware](https://spotlightdelaware.org/feed/), [Delaware Public Media](https://www.delawarepublic.org/politics-government.rss), [WHYY Delaware](https://whyy.org/feed/) |
| FL | [Florida Politics](https://floridapolitics.com/feed/), [Tampa Bay Times](https://www.tampabay.com/arc/outboundfeeds/rss/?outputType=xml), [WUSF](https://www.wusf.org/politics-issues.rss) |
| GA | [Capitol Beat News Service](https://capitol-beat.org/feed/), [Georgia Public Broadcasting](https://www.gpb.org/rss), [Atlanta Civic Circle](https://atlantaciviccircle.org/feed/) |
| HI | [Honolulu Civil Beat](https://www.civilbeat.org/feed/), [Hawaii Public Radio](https://www.hawaiipublicradio.org/local-news.rss), [Star-Advertiser](https://www.staradvertiser.com/feed/) |
| IA | [Radio Iowa](https://www.radioiowa.com/feed/), [Iowa Public Radio](https://www.iowapublicradio.org/ipr-news.rss), [Bleeding Heartland](https://www.bleedingheartland.com/feed/) |
| ID | [Idaho Education News](https://www.idahoednews.org/feed/), [Boise State Public Radio](https://www.boisestatepublicradio.org/news.rss) |
| IL | [Capitol News Illinois](https://capitolnewsillinois.com/feed/), [NPR Illinois](https://www.nprillinois.org/illinois.rss), [Chicago Sun-Times](https://chicago.suntimes.com/feed) |
| IN | [Indiana Public Media](https://indianapublicmedia.org/index.rss) |
| KS | [KCUR](https://www.kcur.org/politics-elections-and-government.rss), [KSNT](https://www.ksnt.com/feed/), [Sunflower State Journal](https://sunflowerstatejournal.com/feed/) |
| KY | [Kentucky Public Radio](https://www.lpm.org/news.rss), [Link NKY](https://linknky.com/feed/) |
| LA | [Louisiana Radio Network](https://louisianaradionetwork.com/feed/), [WWNO](https://www.wwno.org/politics.rss) |
| MA | [CommonWealth Beacon](https://commonwealthbeacon.org/feed/), [GBH News](https://www.wgbh.org/news/politics.rss), [MassLive](https://www.masslive.com/arc/outboundfeeds/rss/?outputType=xml) |
| MD | [Baltimore Banner](https://www.thebaltimorebanner.com/arc/outboundfeeds/rss/?outputType=xml), [WYPR](https://www.wypr.org/index.rss), [Maryland Reporter](https://marylandreporter.com/feed/) |
| ME | [Portland Press Herald](https://www.pressherald.com/feed/), [Bangor Daily News](https://www.bangordailynews.com/feed/), [Maine Public](https://www.mainepublic.org/politics.rss) |
| MI | [Bridge Michigan](https://www.bridgemi.com/rss.xml), [Michigan Public](https://www.michiganpublic.org/politics-government.rss), [MLive](https://www.mlive.com/arc/outboundfeeds/rss/?outputType=xml) |
| MN | [MinnPost](https://www.minnpost.com/feed/), [Star Tribune](https://www.startribune.com/rss/) |
| MO | [St. Louis Public Radio](https://www.stlpr.org/government-politics-issues.rss), [Missourinet](https://www.missourinet.com/feed/), [St. Louis Post-Dispatch](https://www.stltoday.com/search/?f=rss) |
| MS | [Mississippi Today](https://mississippitoday.org/feed/), [Magnolia Tribune](https://magnoliatribune.com/feed/), [Mississippi Free Press](https://www.mississippifreepress.org/feed/) |
| MT | [Montana Free Press](https://montanafreepress.org/feed/), [Montana Public Radio](https://www.mtpr.org/montana-news.rss) |
| NC | [The Assembly](https://www.theassemblync.com/feed/), [WUNC](https://www.wunc.org/politics.rss), [WRAL](https://www.wral.com/news/rss/142/) |
| ND | [InForum](https://www.inforum.com/index.rss), [Prairie Public](https://news.prairiepublic.org/local-news.rss), [KFYR](https://www.kfyrtv.com/arc/outboundfeeds/rss/?outputType=xml) |
| NE | [Flatwater Free Press](https://flatwaterfreepress.org/feed/), [KETV](https://www.ketv.com/topstories-rss) |
| NH | [NHPR](https://www.nhpr.org/nh-news.rss), [InDepthNH](https://indepthnh.org/feed/), [NH Journal](https://nhjournal.com/feed/) |
| NJ | [NJ Spotlight News](https://www.njspotlightnews.org/feed/), [New Jersey Globe](https://newjerseyglobe.com/feed/), [NJ.com](https://www.nj.com/arc/outboundfeeds/rss/?outputType=xml) |
| NM | [NM Political Report](https://nmpoliticalreport.com/feed/), [KUNM](https://www.kunm.org/local-news.rss) |
| NV | [The Nevada Independent](https://thenevadaindependent.com/feed), [Las Vegas Review-Journal](https://www.reviewjournal.com/feed/) |
| NY | [New York Focus](https://nysfocus.com/feed), [City & State NY](https://www.cityandstateny.com/rss/all/), [Gothamist](https://gothamist.com/feed) |
| OH | [Statehouse News Bureau](https://www.statenews.org/government-politics.rss), [Signal Ohio](https://signalohio.org/feed/), [Signal Cleveland](https://signalcleveland.org/feed/) |
| OK | [The Journal Record](https://journalrecord.com/feed/), [NonDoc](https://nondoc.com/feed/), [Oklahoma Watch](https://oklahomawatch.org/feed/) |
| OR | [OPB](https://www.opb.org/arc/outboundfeeds/rss/?outputType=xml), [Willamette Week](https://www.wweek.com/arc/outboundfeeds/rss/?outputType=xml), [The Oregonian](https://www.oregonlive.com/arc/outboundfeeds/rss/?outputType=xml) |
| PA | [WHYY](https://whyy.org/categories/politics-policy/feed/), [PennLive](https://www.pennlive.com/arc/outboundfeeds/rss/?outputType=xml), [WESA](https://www.wesa.fm/politics-government.rss) |
| RI | [The Public's Radio](https://thepublicsradio.org/feed/), [Providence Business News](https://pbn.com/feed/), [WPRI](https://www.wpri.com/feed/) |
| SC | [FITSNews](https://www.fitsnews.com/feed/), [SC Public Radio](https://www.southcarolinapublicradio.org/sc-news.rss) |
| SD | [KELOLAND](https://www.keloland.com/feed/), [Mitchell Republic](https://www.mitchellrepublic.com/index.rss), [Dakota News Now](https://www.dakotanewsnow.com/arc/outboundfeeds/rss/?outputType=xml) |
| TN | [Nashville Banner](https://nashvillebanner.com/feed/), [WPLN](https://wpln.org/feed/) |
| TX | [Texas Tribune](https://www.texastribune.org/feeds/main/), [Texas Observer](https://www.texasobserver.org/feed/), [Texas Standard](https://www.texasstandard.org/feed/) |
| UT | [KUER](https://www.kuer.org/politics-government.rss), [The Salt Lake Tribune](https://www.sltrib.com/arc/outboundfeeds/rss/?outputType=xml), [Utah Policy](https://utahpolicy.com/feed/) |
| VA | [Cardinal News](https://cardinalnews.org/feed/), [Virginia Business](https://virginiabusiness.com/feed/), [VPM](https://www.vpm.org/news.rss) |
| VT | [VTDigger](https://vtdigger.org/feed/), [Seven Days](https://www.sevendaysvt.com/vermont/Rss.xml) |
| WA | [Washington Observer](https://washingtonobserver.substack.com/feed), [Cascade PBS](https://crosscut.com/rss) |
| WI | [Wisconsin Watch](https://wisconsinwatch.org/feed/), [Urban Milwaukee](https://urbanmilwaukee.com/feed/), [WPR](https://www.wpr.org/feed) |
| WV | [Mountain State Spotlight](https://mountainstatespotlight.org/feed/), [WV MetroNews](https://wvmetronews.com/feed/), [Charleston Gazette-Mail](https://www.wvgazettemail.com/search/?f=rss&c=news/politics) |
| WY | [WyoFile](https://wyofile.com/feed/), [Wyoming Public Media](https://www.wyomingpublicmedia.org/rss.xml), [Oil City News](https://oilcity.news/feed/) |

### Layer 3 — Trade press (national)

- [StateScoop](https://statescoop.com/feed/) — dense digital-pillar coverage; the classifier infers the state.
<!-- SOURCES:END -->

### Known gaps & gotchas

- **Feed retention:** ~95 of 171 feeds hold less than 7 days of history. WordPress feeds are paginated backwards automatically; non-WordPress short feeds (public radio, Arc-platform papers, ~44 feeds) ignore pagination and would lose items between weekly runs — which is why the ingest runs daily (dedupe stays weekly).
- **Indiana** has only one verified complementary outlet (most Indiana papers are Gannett, which removed RSS).
- **StateScoop** retains only ~10 items (~a week of their publishing volume).
- `phase0.py` is the original single-feed prototype (Google News query approach) — superseded, kept for reference. The Google News index layer is the planned Phase 1 completeness guarantee.
- **`dedupe.py` windows on the wrong field.** `Raw Events` has no ingestion timestamp, so the window filters on `date` — which the Haiku gate fills with *the date of the government action*, not the publish date. An article ingested today about an action six weeks ago is written with a six-week-old date, falls outside Monday's 7-day window, and never clusters into `Events`. Fixing it needs an `ingested_at` field on `Raw Events` plus a backfill. The congressional pipeline has that field from the start and windows on it, so it doesn't inherit the bug.
- **GAO moved to the federal tracker on 2026-08-20.** It had dominated this feed (21 of 41 events in one window) and, because the trade press covers its reports heavily, the same reports were arriving on the federal tab too — 5 of 6 GAO-actor federal events restated a `Congress Events` row — with nothing deduplicating the two copies. GAO now lives in the federal tracker's `oversight` lane, where a report and the coverage of it cluster into one event. CBO stays here. The 21 GAO rows in `Congress Raw` / `Congress Events` were deleted and re-ingested federally rather than translated: the schemas differ, and re-ingesting is what let them cluster with the coverage.
- **Congressional press volume is recess-sensitive.** In the August 2026 backfill, 11 of 29 press sources returned zero items for the window; every one was verified quiet (newest item predated the window), not broken. Always check the `--dry-run` funnel before assuming a scraper failed.

## Data model

One row per event in `Events`: `Name`, `Notes`, `date`, `state`, `competency` (multi — zero or more of civil-service/procedure/digital/incentives; empty = fits none), `relevance` (1–3, blank when no competency), `topic_tags` (multi — descriptive themes, independent of competency; see `rubric.md`), `activity_type` (bill-introduced/bill-passed/veto/EO/rulemaking/appointment/reorg/RFP-procurement/budget/program-launch/audit-report), `actor_type` (governor/legislature/state agency/statewide official/board-commission/court/university system), `gov_actor`, `why_it_matters`, `source_urls`, `source_outlets`, `article_count`, `Status`. (The previous `pillars`/`significance` model is preserved in the `old_Events` table.)

`Federal Events` mirrors that shape for the executive branch, with the classification fields
unchanged (`competency`, `relevance`, `topic_tags`) and the descriptive fields re-pointed:
`lane` (executive-action / oversight / news / rulemaking), `branch` (executive / congress / judiciary /
multi), `agency` (multi), `instrument_type`, `instrument_id`, `verification` (official /
reported / draft-leaked), `document_url`, plus the same `review_status` / `reviewer_notes`
pair the congressional tables carry. `federal_schema.py` is the single declaration; it imports
the competency and topic-tag vocabularies from `congress_schema.py` so a tag means the same
thing on every tab.
