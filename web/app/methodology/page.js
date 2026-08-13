import usa from "@svg-maps/usa";
import Header from "../header";
import sources from "./sources.json";
import congress from "./congress-sources.json";

export const metadata = {
  title: "Sources & methodology — State Capacity Tracker",
};

const STATE_NAMES = Object.fromEntries(usa.locations.map((l) => [l.id.toUpperCase(), l.name]));

const PILLARS = [
  {
    label: "Civil service",
    color: "#059669",
    desc: "How the state hires, classifies, pays, evaluates, and separates its own workforce — and who holds that authority.",
  },
  {
    label: "Procedure",
    color: "#d97706",
    desc: "The government's own procedural and compliance burden — permitting, licensing, reporting, paperwork — added to or stripped back.",
  },
  {
    label: "Digital",
    color: "#2563eb",
    desc: "How the state builds, buys, staffs, and oversees its own technology and data — IT modernization, AI in government, product vs. project.",
  },
  {
    label: "Incentives",
    color: "#7c3aed",
    desc: "The government's learning/feedback loop — outcome-tied funding, oversight, program evaluation, transparency dashboards, follow-up on existing law.",
  },
];

// Table-of-contents entries — each maps to a section/heading id below.
const TOC = [
  { id: "about", label: "What this is" },
  { id: "how", label: "How events get here" },
  { id: "feed-sources", label: "News-feed sources" },
  { id: "gaps", label: "Known gaps" },
  { id: "governors26", label: "Governors '26 — candidate tracker" },
  { id: "congress", label: "Congress — federal capacity" },
  {
    id: "profiles",
    label: "State profiles — data & sources",
    children: [
      { id: "p-basic", label: "Basic" },
      { id: "p-civil", label: "Civil service" },
      { id: "p-digital", label: "Digital" },
      { id: "p-procedure", label: "Procedure (APA)" },
    ],
  },
];

// Static reference layer (State profiles tab). One block per bucket; mirrors
// static-state-specs.md §3–§4. Each metric carries its named primary source.
const SPEC_BUCKETS = [
  {
    id: "p-basic",
    title: "Basic",
    color: "#0f172a",
    cadence: "Volatile — checked quarterly and after elections.",
    rows: [
      ["Trifecta", "Single party holding governorship + both chambers, else Divided.", "Ballotpedia — State government trifectas", "https://ballotpedia.org/State_government_trifectas"],
      ["Governor (name & party)", "Current sitting officeholder.", "National Governors Association / Ballotpedia", "https://www.nga.org/governors/"],
      ["Term limit, eligibility, next election", "Constitutional limit type; where the current governor sits; year of next race.", "NCSL gubernatorial term-limits table / Ballotpedia", "https://www.ncsl.org/elections-and-campaigns/the-term-limited-states"],
      ["Partisan lean", "Red / Purple / Blue. Locked rule: Purple iff |2024 presidential margin| < 4.0 points (divided government ignored); otherwise Red/Blue by direction. The numeric basis is stored per state.", "2024 presidential margins (Cook PVI / state election authorities)", "https://www.cookpolitical.com/cook-pvi"],
    ],
  },
  {
    id: "p-civil",
    title: "Civil service",
    color: "#059669",
    cadence: "Stable — annual or on-event.",
    rows: [
      ["Collective bargaining", "Three-way: duty to bargain / permits voluntary / prohibits-or-no-provision. Class carve-outs (e.g. police & fire only) noted per state.", "Ballotpedia — Public-sector union policy (NM PELRB / CEPR as statutory backup)", "https://ballotpedia.org/Public-sector_union_policy_in_the_United_States"],
      ["HR authority model & merit protection", "Centralized vs. decentralized HR authority; merit-protected vs. largely at-will workforce. Pulled from NAPA Summary Table 1.", "NAPA × Niskanen — State HR Practices & Benchmarking (2026)", "https://napawash.org/academy-studies/state-hr-policies"],
    ],
  },
  {
    id: "p-digital",
    title: "Digital",
    color: "#2563eb",
    cadence: "Volatile — checked quarterly.",
    rows: [
      ["AI leadership", "Four-way: named CAIO/AI lead / standing AI office / council-or-task-force only / none formal.", "Government Technology AI Tracker; Code for America Government AI Landscape (2026)", "https://www.govtech.com/artificial-intelligence"],
      ["Digital service team", "Whether the state has an in-house digital service team (user-centered research/design + agile product mgmt + data-driven practice).", "Beeck Center DST Tracker / Digital Government Network", "https://digitalgovernmenthub.org/publications/the-state-of-state-digital-transformation/"],
    ],
  },
  {
    id: "p-procedure",
    title: "Procedure (APA)",
    color: "#d97706",
    cadence: "Stable — 2022 vintage; post-2022 statutory changes flagged for manual re-check.",
    rows: [
      ["Rulemaking form, executive/legislative/independent-agency review, impact analysis, periodic review", "Six categories derived from each state's Administrative Procedure Act, extracted directly from the paper's appendix tables A-1–A-6.", "Mercatus — A 50-State Review of Regulatory Procedures (Baugus, Bose & Broughel, 2022)", "https://www.mercatus.org/research/working-papers/50-state-review-regulatory-procedures"],
    ],
  },
];

function siteOf(feedUrl) {
  return new URL(feedUrl).origin;
}

export default function Methodology() {
  const newsroomStates = Object.keys(sources.statenewsroom).sort();
  const newspaperStates = Object.keys(sources.newspapers).sort();
  const newspaperCount = newspaperStates.reduce((n, s) => n + sources.newspapers[s].length, 0);
  const total = newsroomStates.length + newspaperCount + sources.national.length;

  return (
    <main className="wrap">
      <Header active="methodology" />

      <div className="method">
        <nav className="card msec toc" aria-label="On this page">
          <h2>On this page</h2>
          <ol className="toclist">
            {TOC.map((t) => (
              <li key={t.id}>
                <a href={`#${t.id}`}>{t.label}</a>
                {t.children ? (
                  <ol className="tocsub">
                    {t.children.map((c) => (
                      <li key={c.id}>
                        <a href={`#${c.id}`}>{c.label}</a>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </li>
            ))}
          </ol>
        </nav>

        <section className="card msec" id="about">
          <h2>What this is</h2>
          <p>
            A weekly, queryable feed of what state governments are actually doing, classified by
            which of Recoding America&apos;s four state-capacity competencies it advances or undermines — with
            most actions landing outside all four, which is expected:
          </p>
          <ul className="pillarlist">
            {PILLARS.map((p) => (
              <li key={p.label}>
                <span className="chip pillar" style={{ "--c": p.color }}>
                  {p.label}
                </span>{" "}
                {p.desc}
              </li>
            ))}
          </ul>
          <p>
            The tracker covers concrete government <em>actions</em> — bills, vetoes, executive
            orders, rulemaking, appointments, reorganizations, procurement, budgets, program
            launches, audits — not opinion, campaign coverage, or commentary.
          </p>
        </section>

        <section className="card msec" id="how">
          <h2>How events get here</h2>
          <ol className="steps">
            <li>
              <strong>Ingest.</strong> Every Monday morning the pipeline fetches {total}{" "}
              state-government news feeds (the full list is below), paging back through each feed
              until it has the past week of articles.
            </li>
            <li>
              <strong>Pre-screen.</strong> A keyword filter for each competency drops clearly
              irrelevant articles before any model is involved.
            </li>
            <li>
              <strong>Gate 1 — provenance (Claude).</strong> Is the underlying activity an action
              by a <em>state-level</em> government actor in their official capacity?
              Federal-only, city-only, opinion, campaign coverage, and private lawsuits fail here.
            </li>
            <li>
              <strong>Gate 2 — competency (Claude).</strong> Does it touch one of the four
              capacities — civil service, procedure, digital, or incentives? Survivors carry state,
              activity type, and actor type into the raw feed; the competency itself is finalized
              per-event in the next step.
            </li>
            <li>
              <strong>De-duplicate &amp; classify.</strong> One government action usually shows up
              across several outlets. A second model pass clusters the articles into distinct events
              (merging every source URL and outlet onto one row — that&apos;s the &ldquo;N articles
              merged&rdquo; note), then classifies each event against Recoding America&apos;s rubric: its{" "}
              <em>competencies</em> (zero, one, or — when an action genuinely spans two, like
              oversight of a failing IT system — both), a <em>1–3 relevance</em> score for how
              central an example it is (direction-agnostic — undermining a capacity counts as much
              as advancing it), and descriptive <em>topic tags</em>.
            </li>
            <li>
              <strong>Surface.</strong> Events accumulate week over week and are what you see on
              the map.
            </li>
          </ol>
        </section>

        <section className="card msec" id="feed-sources">
          <h2>News-feed sources</h2>
          <p>
            <strong>{total} feeds</strong> in three layers, each doing a different job:{" "}
            {newsroomStates.length} States Newsroom outlets + {newspaperCount} newspapers and
            outlets + {sources.national.length} trade press. The registry is a living list — feeds
            were RSS-verified on {sources.verified}; dead feeds get pruned and new outlets added as
            found.
          </p>

          <h3>Layer 1 — Spine: States Newsroom ({newsroomStates.length} states)</h3>
          <p className="muted">
            Nonprofit statehouse newsrooms, one per state. Dedicated, consistent coverage of state
            government.
          </p>
          <table className="srctable">
            <thead>
              <tr>
                <th>State</th>
                <th>Outlet</th>
              </tr>
            </thead>
            <tbody>
              {newsroomStates.map((st) => (
                <tr key={st}>
                  <td>{STATE_NAMES[st] || st}</td>
                  <td>
                    <a href={`https://${sources.statenewsroom[st]}`} target="_blank" rel="noreferrer">
                      {sources.statenewsroom[st]}
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Layer 2 — Breadth: state newspapers &amp; outlets ({newspaperCount} feeds)</h3>
          <p className="muted">
            Complementary coverage per state, and the only layer covering the{" "}
            {50 - newsroomStates.length} states with no States Newsroom outlet (
            {newspaperStates.filter((s) => !sources.statenewsroom[s]).join(", ")}).
          </p>
          <table className="srctable">
            <thead>
              <tr>
                <th>State</th>
                <th>Outlets</th>
              </tr>
            </thead>
            <tbody>
              {newspaperStates.map((st) => (
                <tr key={st}>
                  <td>{STATE_NAMES[st] || st}</td>
                  <td>
                    {sources.newspapers[st].map((o, i) => (
                      <span key={o.name}>
                        {i > 0 ? " · " : ""}
                        <a href={siteOf(o.feed_url)} target="_blank" rel="noreferrer">
                          {o.name}
                        </a>
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Layer 3 — Trade press (national)</h3>
          <ul>
            {sources.national.map((o) => (
              <li key={o.name}>
                <a href={siteOf(o.feed_url)} target="_blank" rel="noreferrer">
                  {o.name}
                </a>{" "}
                — dense digital-pillar coverage; the classifier infers the state from the article.
              </li>
            ))}
          </ul>
        </section>

        <section className="card msec" id="gaps">
          <h2>Known gaps</h2>
          <ul>
            <li>
              <strong>Feed retention.</strong> Over half of these feeds hold less than 7 days of
              history. The pipeline pages backwards where the feed supports it, but short
              non-paginating feeds (public radio, some metro dailies) can still lose items between
              weekly runs.
            </li>
            <li>
              <strong>Indiana</strong> has only one complementary outlet — most Indiana papers are
              Gannett, which removed RSS.
            </li>
            <li>
              <strong>Coverage follows the press.</strong> An event only enters the tracker if an
              outlet wrote about it; states with thinner statehouse press will look quieter than
              they are.
            </li>
          </ul>
        </section>

        <section className="card msec" id="governors26">
          <h2>Governors &rsquo;26 — candidate tracker</h2>
          <p>
            The main tracker deliberately excludes campaign coverage, so the 2026 gubernatorial
            races (36 states, likely 20+ new governors) get their own layer with the opposite
            filter: what candidates <em>say, plan, and have done</em> about how state government
            builds and runs itself.
          </p>
          <ul>
            <li>
              <strong>Roster.</strong> One row per primary winner or major contender per race,
              researched from primary results, campaign sites, and race coverage, with each
              candidate&apos;s existing platform profiled against the four competencies (the
              &ldquo;platform signal&rdquo; chips). Race ratings reflect Cook Political Report /
              Sabato&apos;s Crystal Ball consensus at time of entry. Curated by hand as races
              develop.
            </li>
            <li>
              <strong>Developments.</strong> A daily pipeline queries Google News per candidate,
              then a model gate keeps only items with governing-agenda substance — policy plans,
              press releases, speeches, actions in current office — and drops horse-race coverage
              (polls, fundraising, attacks, vote counts). Kept items are classified against the
              same four-competency rubric as the main tracker, with statements and plans counting
              the same as enacted actions.
            </li>
            <li>
              <strong>Caveats.</strong> Candidate fields shift quickly — statuses (runoffs,
              withdrawals) are updated manually; platform summaries are point-in-time scrapes of
              campaign sites, stamped with an as-of date.
            </li>
          </ul>
        </section>

        <section className="card msec" id="congress">
          <h2>Congress — federal capacity</h2>
          <p>
            The same four competencies, re-pointed at the <strong>federal</strong> government:
            how Washington hires, procures, builds technology, and runs its own learning loops.
            Coverage is scoped to the {Object.keys(congress.committees).length} committees that
            govern how the federal government operates, plus both party whips and the two
            nonpartisan support agencies. State impact is not a criterion — an action that stays
            entirely inside the federal government is fully in scope.
          </p>

          <h3>Three streams</h3>
          <ul>
            <li>
              <strong>Hearings and bills</strong> come from the{" "}
              <a href="https://api.congress.gov" target="_blank" rel="noreferrer">
                Congress.gov API
              </a>
              , not from scraping. Hearings arrive with room, agenda, witness documents, video,
              and explicit bill linkage. The bills list is everything the seven committees acted
              on in the window — marked up, reported out, or newly referred — dated by the
              committee&apos;s action rather than the bill&apos;s latest floor action, so a bill
              introduced last year appears when its committee takes it up.
            </li>
            <li>
              <strong>Committee and member activity</strong> is scraped from committee and member
              press feeds ({congress.sources.length} sources, listed below). The gate here is
              stricter than provenance: these offices publish mostly messaging, so an item must
              describe a concrete action — a letter sent, a markup held, a report released — not
              a reaction to one.
            </li>
            <li>
              <strong>GAO and CBO</strong> are shown separately. GAO reports are
              oversight-of-capacity almost by construction and run at far higher volume than the
              committees, so mixing them into the committee feed buried it.
            </li>
          </ul>

          <h3>Where the rubric differs from the state tracker</h3>
          <ul>
            <li>
              <strong>Election administration counts.</strong> Senate Rules and House
              Administration are the elections committees. Election systems, voter-roll IT, and
              EAC oversight read as <em>digital</em>; certification and reporting mandates as{" "}
              <em>procedure</em>. The state rubric still excludes it.
            </li>
            <li>
              <strong>
                Appropriations are <em>none</em> by default.
              </strong>{" "}
              A funding level is not a capacity event. It counts only when the funding{" "}
              <em>model</em> changes — multi-year authority, reprogramming flexibility,
              outcome-contingency.
            </li>
            <li>
              <strong>
                Oversight is <em>incentives</em>
              </strong>{" "}
              when it examines whether a program works, and <em>none</em> when it is purely a
              scandal or a partisan dispute.
            </li>
            <li>
              <strong>
                Legislative-branch procedure is <em>procedure</em>
              </strong>{" "}
              — chamber rules and floor process are the legislature changing its own machinery.
            </li>
          </ul>

          <h3>Committees tracked</h3>
          <table className="srctable">
            <thead>
              <tr>
                <th>Committee</th>
                <th>Chair</th>
                <th>Ranking member</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(congress.committees).map(([key, c]) => (
                <tr key={key}>
                  <td>{c.name}</td>
                  <td>{c.chair}</td>
                  <td>{c.ranking}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Press sources ({congress.sources.length})</h3>
          <p className="muted">
            Three kinds. HSGAC and Padilla expose WordPress REST APIs, which return full article
            bodies rather than feed blurbs. Fourteen sources have working RSS. The rest are
            server-rendered listing pages scraped with selector configs — including House
            Oversight, whose published RSS feed has not updated since 2020.
          </p>
          <table className="srctable">
            <thead>
              <tr>
                <th>Source</th>
                <th>Committee</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {congress.sources.map((s) => (
                <tr key={s.name}>
                  <td>
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.name}
                    </a>
                  </td>
                  <td>
                    {congress.committees[s.committee]?.name ||
                      congress.extra[s.committee]?.name ||
                      s.committee}
                  </td>
                  <td className="muted">
                    {{ wp_api: "WordPress API", rss: "RSS", html: "scraped" }[s.kind] || s.kind}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Known gaps</h3>
          <ul>
            <li>
              <strong>CBO contributes almost nothing.</strong> Its only feed is capped at 30 items
              and is dominated by cost estimates — in one recent window, 29 of 30 items were
              post-office naming estimates published the same day, which flushes any substantive
              report out of the feed before it can be read. There is no reports-only CBO feed, and
              the filterable listing page blocks scripted requests.
            </li>
            <li>
              <strong>Member offices go quiet for weeks</strong>, especially during recess. A
              source returning nothing is usually the calendar, not a broken scraper; the ingest
              prints a per-source funnel so the two can be told apart.
            </li>
            <li>
              <strong>Committee attribution is by feed, not by jurisdiction.</strong> A member
              sits on several committees, so an item is filed under the committee whose feed
              carried it. Joint letters are clustered across a whole chamber to avoid duplicate
              events.
            </li>
          </ul>
        </section>

        <section className="card msec" id="profiles">
          <h2>State profiles — data &amp; sources</h2>
          <p>
            The <strong>State profiles</strong> tab is a static reference layer that sits alongside
            the live feed: one row per state across 50 states (DC and territories are out of scope
            for v1). It&apos;s a separate dataset from the news feed — every value is a metric that
            is comparable across all states and traceable to a single named primary source.
          </p>
          <p className="muted">
            Two rules govern it. <strong>Named primary sources only</strong> — each field is filled
            from the source named below (or the state&apos;s own statute), never from AI-generated
            summary sites, which frequently fabricate citations in this subject area. And{" "}
            <strong>every value carries provenance</strong> — each metric group shows its source
            link and an &ldquo;as of&rdquo; date inline on the profile card, so you can see how
            fresh each value is.
          </p>

          {SPEC_BUCKETS.map((b) => (
            <div key={b.id} id={b.id} className="specbucket">
              <h3 style={{ color: b.color }}>{b.title}</h3>
              <p className="muted cadence">{b.cadence}</p>
              <table className="srctable">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>What it measures</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((r) => (
                    <tr key={r[0]}>
                      <td>{r[0]}</td>
                      <td className="defcell">{r[1]}</td>
                      <td>
                        <a href={r[3]} target="_blank" rel="noreferrer">
                          {r[2]}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
