# State Capacity Tracker — v1 Brief & Build Plan

*Working title. A weekly, queryable feed of what state governments are actually doing, categorized into Recoding America's pillars.*

This document is two things at once: the product brief (what we're building and why) and the build spec you can hand to Claude Code to start the repo. Build it phase by phase; each phase produces something real.

---

## 1. What this is

A pipeline that ingests media about state government, keeps only the items that represent **real government activity** in Recoding America's domains, de-duplicates them into distinct *events*, and surfaces them as a **weekly digest** plus a **queryable view**. The point is not to collect news — that part is commoditized. The point is the weekly, categorized read of *what moved* across 50 states.

## 2. Who it's for, and the job

- **Primary user (v1):** the Recoding America team. This is an **internal-first** tool whose output travels outward *through people*, not a published dashboard.
- **Lead job:** equip colleagues to walk into any partner/funder conversation and speak credibly about what's happening in any state, in our domains.
- **v2 jobs (later):** Recoding America as field authority (thought leadership), partner-state intel + peer benchmarking, funder-facing landscape.
- **Why this matters for the build:** because v1 readers apply their own judgment, v1 does **not** need publish-grade precision. The bar is "good enough that a sharp person can scan it and pull the real signal." That buys speed now; precision graduates the pipeline into the v2 external versions later.

## 3. What counts as signal (the filter)

Each item passes two gates, then gets a rank:

1. **Provenance gate** — is the underlying activity an action by a government actor in their official capacity? Bill (introduced *or* passed), executive order, rulemaking, appointment, agency reorg, RFP/procurement, budget move, program launch, official audit/report. *The test is about the **activity**, not the publisher* — a vendor press release announcing a state contract award counts, because the award is a government action.
   - Out: think-tank reports, advocacy, campaign promises, punditry.
2. **Pillar gate** — does it touch one of: **Deproceduralization / Regulatory simplification**, **Digital & tech transformation**, **Civil service & workforce reform**?
3. **Significance** is a *ranking* for ordering the digest, **not** a keep/drop gate. Never silently drop something that might matter — just sort it lower.

**Scope:** 50 states, state-level activity for v1. Federal is a v2 toggle.

## 4. Sources

Three source *types*, each doing a different job:

- **Spine — News from the States (States Newsroom).** Purpose-built for "what did state governments do," all 50 capitals, free and reprintable, and itself a syndication hub. Non-negotiable. *Caveat:* footprint gaps — independent/for-profit outlets (e.g., Colorado Sun, The Journal Record) aren't in its network, so it won't catch every story alone.
  - Feeds: per-state at `<outlet-domain>/feed/localFeed`; curated top-stories feed; topic feeds.
- **Catch-all index — Google News query feeds.** This is the *completeness guarantee*. Google indexes essentially every outlet, so any story is reachable here. Build narrow `"<state>" "<pillar keyword>"` queries. **The guarantee is bounded by your keywords, not by which outlets you watch.**
  - Format: `https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en`
  - Gotchas: 100-item cap per feed (keep queries narrow); links are base64-encoded and redirect (needs a decode step).
- **Trade press — StateScoop** (`statescoop.com/feed`). Dense, high-signal coverage for the **digital pillar specifically** (CIO moves, modernization, procurement, cyber). National/cross-state, so the classifier must infer the state from the article body. Won't cover deproc or civil service well. Peers for later/federal: FedScoop, Route Fifty, Government Technology.
- **Pending (Layer C, strong v1 candidate) — government press releases.** Governors' offices and agencies publish primary-source releases (the purest provenance, lowest noise). More setup per state; worth pulling into v1 at least for governors' offices.
- **Optional maximal — GDELT.** Free global news index, catches even more than Google News, but a raw firehose with heavy noise. Not needed for v1.

**Three principles that fell out of testing the sources:**

1. **Track events, not articles.** One government action shows up across 8+ outlets. Cluster duplicates into a single event or the digest drowns in repeats.
2. **Keywords are the highest-leverage and highest-risk component.** Misses come from the words you chose, not the outlets you watch. (A "benefits modernization" query misses an "IT-office reorg + layoffs" story entirely.) The pillar keyword lists are where your deproc/licensing/civil-service vocab pays off — treat them as a living, reviewed artifact.
3. **Completeness comes from the index layer**, not any one newsroom. Spine you trust + index that catches the rest.

## 5. Pipeline architecture

```
[Ingest]  →  [Cluster into events]  →  [Classify + gate]  →  [Store]  →  [Surface]
  RSS           dedup near-dupes        provenance/pillar    Airtable    weekly digest
  feeds         across outlets          + tags + rank                    + query view
```

1. **Ingest** — pull all feeds, dump raw items to a staging table. Cheap, broad, dumb.
2. **Cluster** — group near-duplicate items (same event, many outlets) into one event record. Keep all source URLs on the event.
3. **Classify + gate** — for each event, run the two gates; if it passes, tag it (see data model) and write a one-line "what happened." Pre-screen with a cheap keyword match *before* the LLM call to control cost; classify survivors with a fast Claude model.
4. **Store** — one row per surviving event in Airtable, queryable by state / pillar / date.
5. **Surface** — auto-draft a weekly digest from the week's high-significance events, grouped by pillar (or state); the team queries the table before meetings. "Machine drafts, human skims."

## 6. Data model (one row per *event*)

| Field | Notes |
|---|---|
| `event_id` | stable id for the clustered event |
| `date` | date of the government action (or earliest article) |
| `state` | 2-letter; from feed metadata or inferred by classifier |
| `pillars` | one or more: deproc / digital / civil-service |
| `activity_type` | bill-introduced, bill-passed, EO, rulemaking, appointment, reorg, RFP/procurement, budget, program-launch, audit/report |
| `gov_actor` | which body/office (e.g., "CO Office of Information Technology") |
| `headline` | one-line "what happened," your words |
| `significance` | 1–5 (ranking only) |
| `why_it_matters` | optional 1-line for the digest |
| `source_urls` | all clustered articles |
| `source_outlets` | publishers |
| `status` | optional (introduced / enacted / etc.) |

## 7. Tech stack — mapped to your tools

- **Language:** Python (matches your prior Anthropic-API pipelines).
- **RSS:** `feedparser`; small decoder for Google News redirect URLs.
- **Classification:** Anthropic API — a fast model for per-event gating/tagging, a stronger model for the weekly synthesis.
- **Storage:** **Airtable** for v1 (you already live there; instant query/share, no DB to run). Swap to Postgres only if you outgrow it.
- **Scheduler / engine:** **GitHub Actions cron** — free scheduled compute, no server. This runs the weekly pipeline.
- **Digest delivery:** Slack (or email) — auto-posted weekly.
- **Query UI (phase 3):** **Next.js on Vercel**, read-only, reading from Airtable, filter by state/pillar/date.
- **Repo + secrets:** GitHub. Keep the Anthropic key + Airtable token in **GitHub Actions secrets** and **Vercel env vars** — never commit them.

## 8. Build phases (for Claude Code)

- **Phase 0 — One feed, end to end (start here).** One Google News query → fetch → classify a single item → write one row to Airtable. Proves the spine and lets you see *real classifier output* immediately. (~an afternoon.)
- **Phase 1 — Breadth + quality.** Add all source types, the keyword matrix, event clustering, and the full classification schema. Run manually and **inspect output**: tune the classifier prompt and keyword lists. This is the phase that determines whether the product is good.
- **Phase 2 — Automate.** GitHub Actions weekly cron; auto-generate the digest; deliver to Slack/email.
- **Phase 3 — Surface.** Vercel + Next.js read-only dashboard over Airtable. The "scan before a meeting" view.
- **Phase 4 — v2.** Add government press releases, the federal toggle, and polish toward external/field-authority quality.

## 9. Build notes & gotchas

- **Cost control:** narrow Google News queries + a keyword pre-screen before any LLM call. Don't classify the raw firehose.
- **Google News URLs** are encoded and redirect — decode to the real publisher link before storing (existing snippets/workflows do this).
- **100-item cap** per Google News search feed — narrow queries, not broad ones.
- **State inference:** trade-press and national feeds don't carry a state tag; the classifier infers it.
- **Human-in-the-loop:** the only thing you must review by hand early is *classifier accuracy and keyword coverage*. Everything else can run unattended.

## 10. Parked / open questions

- **Relationship to the AI research librarian** (with Galen): sibling tool, or another surface of it? Same Living-Overview-plus-queryable-tracker shape. Decide before Phase 3.
- Digest grouping: by pillar or by state as the primary cut?
- Whether to promote government press releases (Layer C) into Phase 1 rather than Phase 4.
