# Static State Specs — Data Spec for the State-Wide Intelligence Page

**Purpose.** Define the *static* reference layer that sits alongside the live news feed on the state tracker. One row per state. Every field is a metric that is (a) genuinely comparable across all states and (b) traceable to a single authoritative source. This file is the build spec for Claude Code: it defines the Airtable schema, the source for every field, extraction notes, data-quality rules, and the website view.

**Coverage.** 50 states = **50 rows**. DC and territories are out of scope for v1 — several source datasets don't cover them comparably, and including them breaks the "easily comparable" goal.

**Guiding principle: quality over breadth.** Each field below carries a **Comparability** rating. `High` = clean, defensible, source publishes a per-state value. `Medium` = requires a judgment call or manual extraction; reproducible only if we fix the rule. Cut `Medium` fields first if the page feels noisy. Do not add fields that aren't on this list without giving them the same treatment (definition + single source + as-of date).

---

## 1. Sourcing rules (read before populating anything)

These exist because fabricated-citation SEO sites are a known contaminant in this exact subject area.

1. **Named primary sources only.** Every field has an assigned source in Section 3. Populate *only* from that source (or the state's own statute/site). Do **not** fill cells from AI-generated summary sites, content farms, or secondary blogs, even if they look authoritative and cite statutes — citations on those sites are frequently fabricated.
2. **Every value carries provenance.** Each metric group has a paired `*_source` (URL) and `*_asof` (date) field. No value lands in Airtable without both.
3. **Enums over prose.** Anything used to filter, sort, or color the map is a fixed enum (defined per field). Free text goes only in `*_note` fields.
4. **Volatile vs. stable.** Stable fields (trifecta, collective bargaining, Mercatus APA, NAPA) can be batch-loaded once. Volatile fields (governor, next election, AI lead) need an `asof` date and a refresh cadence — see Section 5.

---

## 2. Airtable schema — table `State Specs`

One record per state. Field types in brackets. Enum options are the *only* allowed values.

### Identity
| Field | Type | Notes |
|---|---|---|
| `state` | Single line text | Full name, e.g. "New York" |
| `postal` | Single line text | "NY" — primary key for joins / map / news-feed link |
| `record_last_updated` | Last modified time | Auto |

### A. Basic
| Field | Type | Allowed values / format |
|---|---|---|
| `partisan_lean` | Single select | `Red` · `Purple` · `Blue` |
| `partisan_lean_basis` | Single line text | The numeric inputs behind the call (see 3.A1) |
| `trifecta` | Single select | `Republican` · `Democratic` · `Divided` |
| `governor_name` | Single line text | — |
| `governor_party` | Single select | `R` · `D` · `Independent` |
| `gov_term_limit` | Single select | `No limit` · `2 consecutive` · `2 lifetime` · `Other` |
| `gov_terms_remaining` | Single select | `In final allowed term` · `Eligible for re-election` · `Term-limited / cannot run again` |
| `gov_next_election` | Number (year) | e.g. 2026 |
| `basic_source` | URL | — |
| `basic_asof` | Date | — |

### B. Civil service
| Field | Type | Allowed values / format |
|---|---|---|
| `collective_bargaining` | Single select | `Duty to bargain` · `Permits voluntary` · `Prohibits / no provision` |
| `cb_note` | Long text | Carve-outs (e.g. "police & fire only") |
| `hr_authority_model` | Single select | `Centralized` · `Decentralized` · `Hybrid` (from NAPA — see 3.B2) |
| `merit_protection` | Single select | `Classified / merit-protected majority` · `Largely at-will` · `Mixed` |
| `napa_note` | Long text | Other comparable NAPA fields we choose to surface |
| `civilservice_source` | URL | — |
| `civilservice_asof` | Date | — |

### C. Digital
| Field | Type | Allowed values / format |
|---|---|---|
| `ai_leadership` | Single select | `Named CAIO/AI lead` · `AI leadership office` · `Council/task force only` · `None formal` |
| `digital_service_team` | Single select | `Yes` · `No` · `Disbanded` |
| `digital_source` | URL | — |
| `digital_asof` | Date | — |

### D. Procedure (Mercatus APA)
| Field | Type | Allowed values / format |
|---|---|---|
| `rulemaking_form` | Single select | `Formal` · `Informal` · `Both/Mixed` |
| `executive_review` | Single select | `Yes` · `No` |
| `executive_review_who` | Single line text | e.g. "Governor's office", "Budget office" |
| `legislative_review` | Single select | `None` · `Advisory review` · `Can suspend/veto` · `Approval required` |
| `independent_agency_review` | Single select | `Yes` · `No` |
| `impact_analysis` | Multiple select | `Small-business impact` · `Fiscal impact` · `Cost-benefit` · `None` |
| `periodic_review` | Single select | `Yes` · `No` |
| `procedure_source` | URL | — |
| `procedure_asof` | Date | — |

---

## 3. Per-metric reference (definition · source · extraction)

### A. Basic

**A1. `partisan_lean` — Comparability: Medium.** Red/blue/purple is a judgment metric, so the *rule* must be fixed and reproducible. **Locked rule:** classify `Purple` iff the most recent presidential margin is **under 4.0 points** (`|2024 margin| < 4`). Government control being split does **not** affect the call. Otherwise `Red`/`Blue` by direction of the 2024 presidential result. Store the inputs in `partisan_lean_basis` (e.g. "2024 pres margin R+1.2; |margin|<4 → Purple") so the call is auditable.
- Source: Cook Partisan Voting Index (state-level) for the lean; presidential margins via 270toWin or the state's election authority. Do not eyeball it from a blog.

**A2. `trifecta` — Comparability: High.** Single party holds governorship + both legislative chambers, else `Divided`. (Nebraska's unicameral, officially nonpartisan, is handled by Ballotpedia's methodology — follow it.)
- Source: Ballotpedia, *State government trifectas*. Cross-check partisan composition against NCSL.

**A3. `governor_name` / `governor_party` — Comparability: High. VOLATILE.** Current officeholder.
- Source: National Governors Association (governors.org) or Ballotpedia. Always set `basic_asof`.

**A4. Gov term fields — Comparability: High.** `gov_term_limit` = the constitutional limit type. `gov_terms_remaining` = where the *current* governor sits relative to it. `gov_next_election` = year of next gubernatorial election.
- Sources: NCSL gubernatorial term-limits table (limit type); Ballotpedia (current incumbent's eligibility + next election year). Note: term-limit *type* is stable; eligibility is VOLATILE (changes when a governor is re-elected).

### B. Civil service

**B1. `collective_bargaining` — Comparability: High (with caveat).** Three-way classification: states that impose a *duty to bargain*, states that *permit voluntary* bargaining, and states that *prohibit or have no provision*. Caveat (per EPI/CEPR): classification is inherently imprecise because many states rely on vague statutes or case law and vary by employee class — capture class carve-outs in `cb_note` (e.g. "police & fire only" for TX).
- Source: Ballotpedia, *Public-sector union policy in the United States*, for the three-bucket classification. Verify against the statutory compilation (NM PELRB *Public Sector Collective Bargaining by State*) or Sanes & Schmitt (CEPR) where a state is ambiguous. North/South Carolina = `Prohibits`; New York = `Duty to bargain`; etc.

**B2. NAPA fields — Comparability: Medium (manual extraction needed).** The NAPA / Niskanen *State Human Resources Practices and Benchmarking* study (final report + two spreadsheets, completed Feb 2026) covers hiring/recruitment, compensation/classification, performance management, merit protection, grievance, and disciplinary procedures across all 50 states. **The spreadsheets are the data source — Claude Code must open them and pick the cleanly comparable columns.** Recommended starting set (only those that come through as consistent per-state values): HR authority model (centralized vs. decentralized → `hr_authority_model`) and merit-protected vs. at-will posture (→ `merit_protection`). Keep additional comparable columns in `napa_note` rather than minting new enum fields until we see the data.
- Source: napawash.org/academy-studies/state-hr-policies → "State HR Practices Benchmarking" (state profiles) and "Summary Tables" workbooks. **Action for Claude Code:** download both `.xlsx`, inventory the columns, and report back which are 50-state-complete before we lock the enum values. (Note: the NAPA asset host isn't directly reachable from the sandbox network — fetch via the browser tool or download locally and add to the repo.)

### C. Digital

**C1. `ai_leadership` — Comparability: High. VOLATILE.** Four-way: a named individual AI lead (`Named CAIO/AI lead`), a standing AI office (`AI leadership office`), only a council/task force, or nothing formal. As of early 2026 examples: NY/NJ/GA have named individuals; UT/CT/RI/VT created offices — verify each state at populate time.
- Sources: Government Technology *AI Tracker*; Code for America *Government AI Landscape Assessment* (2026 edition, research culminated March 2026). NASCIO for tech-leadership context.

**C2. `digital_service_team` — Comparability: High.** Whether the state has an in-house digital service team. The DSN defines a DST as an in-house team with user-centered research/design, agile product management, and data-driven practice, mandated to build/improve public-facing services.
- Source: Beeck Center (Georgetown) *Government Digital Service Team Tracker* and the *State of State Digital Transformation* interactive map. (The DSN, Digital Benefits Network, and State CDO Network merged into the **Digital Government Network** in 2026 — same underlying trackers.)

### D. Procedure — Mercatus APA review

**Comparability: High, vintage caveat.** All six fields come from one dataset: Baugus, Bose & Broughel, *A 50-State Review of Regulatory Procedures* (Mercatus, 2022), derived from each state's Administrative Procedure Act. The six categories map directly to the schema fields:

- `rulemaking_form` — formal vs. informal rulemaking.
- `executive_review` (+ `executive_review_who`) — whether a budget office / governor / other executive office must review new rules.
- `legislative_review` — strength of the legislature's role, from none up to required approval or veto without the governor.
- `independent_agency_review` — whether a proposed rule must clear an independent agency.
- `impact_analysis` — which impact requirements apply (small-business, fiscal, cost-benefit).
- `periodic_review` — whether existing rules face mandated periodic review.

Source: the working paper PDF **plus** the *50 State Supplementary Procedure Reports* (per-state detail) on the Mercatus page. **Caveat:** 2022 vintage. APA structure is stable, but several states have since passed red-tape / periodic-review / REINS-style measures. Set `procedure_asof` to the Mercatus date and flag any state where you know of a post-2022 change for manual verification against the current state code.

---

## 4. Source index (canonical URLs)

| Bucket | Source | URL |
|---|---|---|
| Trifecta | Ballotpedia — State government trifectas | ballotpedia.org/State_government_trifectas |
| Partisan composition | NCSL | ncsl.org |
| Partisan lean | Cook PVI / 270toWin | — |
| Governor | National Governors Association | governors.org |
| Gov term limits | NCSL term-limits table | ncsl.org |
| Collective bargaining | Ballotpedia — Public-sector union policy | ballotpedia.org |
| Collective bargaining (statute backup) | NM PELRB compilation / CEPR (Sanes & Schmitt) | — |
| Civil service / HR | NAPA × Niskanen State HR Benchmarking | napawash.org/academy-studies/state-hr-policies |
| AI leadership | GovTech AI Tracker; Code for America AI Landscape Assessment | govtech.com ; codeforamerica.org |
| Digital service teams | Beeck Center DST Tracker / Digital Government Network | beeckcenter.georgetown.edu ; digitalgovernmenthub.org |
| Procedure | Mercatus 50-State Review of Regulatory Procedures | mercatus.org/research/working-papers/50-state-review-regulatory-procedures |

---

## 5. Refresh cadence

- **Stable (annual or on-event):** trifecta, term-limit type, collective bargaining, NAPA fields, Mercatus fields.
- **Volatile (check quarterly + after elections):** `governor_*`, `gov_terms_remaining`, `gov_next_election`, `ai_leadership`, `partisan_lean`.
- Treat `*_asof` as the source of truth for staleness; surface it on the site (see 6) so users can see how fresh each value is.

---

## 6. Website view

A read-only intelligence layer over the Airtable. Three views, sharing one data source:

1. **Map + picker (landing).** US map colored by a default lens (toggle between `trifecta` and `partisan_lean`). Click/select a state → opens its profile. Dropdown picker for accessibility.
2. **State profile card.** Four sections matching the buckets (Basic / Civil Service / Digital / Procedure). Each metric renders as label → value (enum value as a colored chip), with a small source link and the `asof` date inline so freshness is visible. Pull the **existing live news feed** for that state into the top of the card (join on `postal`).
3. **Compare view.** A sortable, filterable 50-row table — filter by any enum (e.g. "Republican trifecta + Prohibits collective bargaining + has a digital service team"), and a side-by-side mode for 2–4 selected states. This is where the "easily comparable" payoff lives.

Out of scope for v1 (note for later): any composite "reform-readiness" score that blends these fields. Tempting, but it bakes in weighting judgments — ship the raw comparable layer first.

---

## 7. Build sequence for Claude Code

1. Create the `State Specs` table with the exact field types/enums in Section 2.
2. Batch-load the **stable** fields from the named trackers: trifecta, collective bargaining, all six Mercatus fields. One source per field; write `*_source` + `*_asof` as you go.
3. Open the two NAPA `.xlsx` workbooks, inventory columns, confirm which are 50-state-complete, then load `hr_authority_model` + `merit_protection` (report back before locking any added NAPA enums).
4. Load the **volatile** fields with explicit `asof` dates: governor, term eligibility, next election, AI leadership, partisan lean (apply the fixed rule in 3.A1).
5. Build the website views in Section 6 off the Airtable API, then wire the existing news feed into the profile card on `postal`.

**Decision (confirmed):** `Purple` threshold in 3.A1 = presidential margin strictly under 4.0 points; divided government is ignored.
