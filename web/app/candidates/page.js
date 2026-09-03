"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Header from "../header";

const STATE_NAMES = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa",
  KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont",
  VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin",
  WY: "Wyoming",
};

const RATING_ORDER = {
  "Toss-up": 0, "Lean R": 1, "Lean D": 1, "Likely R": 2, "Likely D": 2,
  "Safe R": 3, "Safe D": 3,
};

const COMPETENCIES = ["civil-service", "procedure", "digital", "incentives"];

const STATUS_ORDER = {
  incumbent: 0, "primary-winner": 1, "runoff-pending": 2,
  "presumptive-nominee": 3, "major-contender": 4,
};

// Recent-results windows. `null` = all time.
const WINDOWS = [
  ["7", "7 days", 7],
  ["30", "30 days", 30],
  ["90", "90 days", 90],
  ["all", "All", null],
];

// YYYY-MM-DD string cutoff for N days ago (local date, matches Airtable ISO dates).
function cutoffFor(days) {
  if (days == null) return null;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function sortCands(cands) {
  return [...cands].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
      a.party.localeCompare(b.party) ||
      a.name.localeCompare(b.name)
  );
}

const PARTY_COLORS = { R: "#b3453c", D: "#3c6cb3", I: "#8a7a4a", L: "#a68f3c" };

function ratingClass(r) {
  if (r === "Toss-up") return "tossup";
  if ((r || "").startsWith("Lean")) return "lean";
  return "settled";
}

function PartyChip({ party }) {
  if (!party) return null;
  return (
    <span className="partychip" style={{ "--pc": PARTY_COLORS[party] || "#777" }}>
      {party}
    </span>
  );
}

function TitleToggle({ open, onClick, children }) {
  return (
    <button className="itemtitle" onClick={onClick} aria-expanded={open}>
      <span className="caret">{open ? "\u25be" : "\u25b8"}</span>
      {children}
    </button>
  );
}

// One development, in the candidate card and in the main feed. The row is the
// short title; `headline` is a full sentence by contract and was what this row
// used to print, which is why these lists read as a wall of prose.
function DevItem({ d, showWho }) {
  const [open, setOpen] = useState(false);
  // Keyed to what the body can actually show. `headline` is not rendered there
  // — it restates short_title, the same cut the Federal and Congress tabs take
  // — so it must not open an otherwise empty drawer.
  const hasMore = Boolean(d.why_it_matters);
  return (
    <li className="devitem">
      <div className="devmeta">
        <time>{d.date}</time>
        {showWho ? <span className="statechip">{d.state}</span> : null}
        {showWho ? <span className="devcand">{d.candidate}</span> : null}
        {(d.competency || []).map((x) => (
          <span key={x} className="minichip">{x}</span>
        ))}
        {showWho && d.article_count > 1 ? (
          <span className="devsources">· {d.article_count} sources</span>
        ) : null}
      </div>
      {hasMore ? (
        <TitleToggle open={open} onClick={() => setOpen(!open)}>
          {d.short_title}
        </TitleToggle>
      ) : d.urls[0] ? (
        <a className="devheadline" href={d.urls[0]} target="_blank" rel="noreferrer">
          {d.short_title}
        </a>
      ) : (
        <span className="devheadline">{d.short_title}</span>
      )}
      {open ? (
        <div className="itembody">
          {/* One prose block, and it is why_it_matters — the cut the Federal
              and Congress tabs take, for the same reason. `headline` is a full
              sentence restating the title and `summary` opens on the same
              facts; the why is the one thing the title cannot carry. Both stay
              on the API payload for the digest and the review export. */}
          <p className="itemsummary">{d.why_it_matters}</p>
          {d.urls[0] ? (
            <a className="sourcelink" href={d.urls[0]} target="_blank" rel="noreferrer">
              Read the source →
            </a>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function CandidateRow({ c, devs }) {
  const [open, setOpen] = useState(false);
  const recent = devs.slice(0, 3);
  const hasMore = c.platform_summary || recent.length > 0;
  return (
    <div className="candrow">
      <div className="candtop">
        <PartyChip party={c.party} />
        <span className="candname">{c.name}</span>
        {c.role ? <span className="candrole">{c.role}</span> : null}
        <span className={`candstatus s-${c.status}`}>{c.status.replace(/-/g, " ")}</span>
        {(c.competency_signals || []).map((s) => (
          <span key={s} className="minichip">{s}</span>
        ))}
        <span className="candlinks">
          {c.website ? (
            <a href={c.website} target="_blank" rel="noreferrer">site</a>
          ) : null}
          {hasMore ? (
            <button className="candmore" onClick={() => setOpen(!open)}>
              {open ? "less −" : `more +${devs.length ? ` (${devs.length})` : ""}`}
            </button>
          ) : null}
        </span>
      </div>
      {open ? (
        <div className="candbody">
          {c.platform_summary ? (
            <p className="candsummary">
              {c.platform_summary}
              {c.platform_asof ? (
                <span className="asof"> — platform as of {c.platform_asof}</span>
              ) : null}
            </p>
          ) : null}
          {recent.length ? (
            <ul className="devlist">
              {recent.map((d) => (
                <DevItem key={d.id} d={d} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RaceCard({ r, devsByCand, recent }) {
  const [open, setOpen] = useState(false);
  const totalDevs = r.cands.reduce(
    (n, c) => n + (devsByCand.get(`${c.state}|${c.name}`) || []).length,
    0
  );
  return (
    <section className={`racecard ${open ? "open" : ""}`}>
      <div className="racehead">
        <button className="racetoggle" onClick={() => setOpen(!open)}
                aria-expanded={open}>
          <span className="racecaret">{open ? "▾" : "▸"}</span>
          <span className="racestate">{STATE_NAMES[r.state] || r.state}</span>
          <span className="statechip">{r.state}</span>
          {r.rating ? (
            <span className={`ratingchip ${ratingClass(r.rating)}`}>{r.rating}</span>
          ) : null}
          {r.race_type === "open" ? <span className="openchip">open seat</span> : null}
          <span className="racecount">
            {r.cands.length} cand{r.cands.length === 1 ? "" : "s"}
            {recent ? <span className="recentdot" title="recent activity" /> : null}
          </span>
        </button>
        {r.primary_date ? (
          <span className="primaryinfo">
            primary {r.primary_date}
            {r.primary_held ? " ✓" : ""}
          </span>
        ) : null}
        <Link href={`/states/${r.state}`} className="raceprofile">profile →</Link>
      </div>
      {open ? (
        <div className="candlist">
          {r.cands.map((c) => (
            <CandidateRow
              key={c.id}
              c={c}
              devs={devsByCand.get(`${c.state}|${c.name}`) || []}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export default function Candidates() {
  const [candidates, setCandidates] = useState(null);
  const [devs, setDevs] = useState([]);
  const [error, setError] = useState(null);
  const [ratingF, setRatingF] = useState("all"); // all | competitive | open
  const [partyF, setPartyF] = useState("all");
  const [signalF, setSignalF] = useState("all");
  const [windowF, setWindowF] = useState("30"); // 7 | 30 | 90 | all
  // Developments matching none of the four competencies are hidden by default,
  // as on the state map. Without this escape hatch they were unreachable —
  // more than half the feed was invisible with no way to see it.
  const [showOther, setShowOther] = useState(false);

  const cutoff = useMemo(
    () => cutoffFor(WINDOWS.find(([v]) => v === windowF)?.[2]),
    [windowF]
  );

  useEffect(() => {
    fetch("/api/candidates")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setCandidates(d.candidates)))
      .catch((e) => setError(String(e)));
    fetch("/api/candidate-developments")
      .then((r) => r.json())
      .then((d) => setDevs(d.developments || []))
      .catch(() => setDevs([]));
  }, []);

  const filtered = useMemo(() => {
    return (candidates || []).filter((c) => {
      if (c.status === "withdrawn" || c.status === "defeated") return false;
      if (ratingF === "competitive" && ratingClass(c.race_rating) === "settled") return false;
      if (ratingF === "open" && c.race_type !== "open") return false;
      if (partyF !== "all" && c.party !== partyF) return false;
      if (signalF !== "all" && !(c.competency_signals || []).includes(signalF)) return false;
      return true;
    });
  }, [candidates, ratingF, partyF, signalF]);

  const races = useMemo(() => {
    const byState = new Map();
    for (const c of filtered) {
      if (!byState.has(c.state)) byState.set(c.state, []);
      byState.get(c.state).push(c);
    }
    const out = [...byState.entries()].map(([state, cands]) => {
      const meta = cands[0];
      return { state, cands: sortCands(cands), rating: meta.race_rating, race_type: meta.race_type,
               primary_date: meta.primary_date, primary_held: meta.primary_held };
    });
    out.sort(
      (a, b) =>
        (RATING_ORDER[a.rating] ?? 9) - (RATING_ORDER[b.rating] ?? 9) ||
        a.state.localeCompare(b.state)
    );
    return out;
  }, [filtered]);

  // Everything below the summary strip respects the selected time window.
  const windowedDevs = useMemo(
    () => (cutoff ? devs.filter((d) => d.date && d.date >= cutoff) : devs),
    [devs, cutoff]
  );

  const devsByCand = useMemo(() => {
    const m = new Map();
    for (const d of windowedDevs) {
      const k = `${d.state}|${d.candidate}`;
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(d);
    }
    return m;
  }, [windowedDevs]);

  // States with at least one windowed development — drives the "recent" dot.
  const statesWithActivity = useMemo(
    () => new Set(windowedDevs.map((d) => d.state)),
    [windowedDevs]
  );

  // Look up a development's candidate so the party/race pills can filter the feed.
  const candByKey = useMemo(() => {
    const m = new Map();
    for (const c of candidates || []) m.set(`${c.state}|${c.name}`, c);
    return m;
  }, [candidates]);

  const rafDevs = useMemo(
    () =>
      windowedDevs
        .filter((d) => showOther || (d.competency || []).length)
        .filter((d) => {
          if (signalF !== "all" && !(d.competency || []).includes(signalF)) return false;
          const c = candByKey.get(`${d.state}|${d.candidate}`);
          if (partyF !== "all" && c?.party !== partyF) return false;
          if (ratingF === "competitive" && (!c || ratingClass(c.race_rating) === "settled"))
            return false;
          if (ratingF === "open" && c?.race_type !== "open") return false;
          return true;
        })
        .slice(0, 60),
    [windowedDevs, signalF, partyF, ratingF, candByKey, showOther]
  );

  const total = candidates
    ? candidates.filter((c) => c.status !== "withdrawn" && c.status !== "defeated").length
    : 0;
  const nStates = candidates ? new Set(candidates.map((c) => c.state)).size : 0;

  return (
    <main className="wrap">
      <Header />

      {/* No tab highlights this view any more — it is reached from the State Map
          page — so the page names itself. */}
      <div className="pagelead">
        <h2 className="pagetitle">Governors &rsquo;26</h2>
      </div>

      {error ? <p className="error">Error: {error}</p> : null}

      <section className="panel racepanel">
        <div className="panelrow">
          <span className="panelrowlabel">Recent results</span>
          <div className="pillarbtns">
            {WINDOWS.map(([v, label]) => (
              <button key={v} className={`pill ${windowF === v ? "on" : ""}`}
                      onClick={() => setWindowF(v)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="panelrow">
          <span className="panelrowlabel">Races</span>
          <div className="pillarbtns">
            {[["all", "All"], ["competitive", "Competitive"], ["open", "Open seats"]].map(
              ([v, label]) => (
                <button key={v} className={`pill ${ratingF === v ? "on" : ""}`}
                        onClick={() => setRatingF(v)}>
                  {label}
                </button>
              )
            )}
          </div>
        </div>
        <div className="panelrow">
          <span className="panelrowlabel">Party</span>
          <div className="pillarbtns">
            {[["all", "All"], ["R", "R"], ["D", "D"], ["I", "Ind"]].map(([v, label]) => (
              <button key={v} className={`pill ${partyF === v ? "on" : ""}`}
                      onClick={() => setPartyF(v)}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="panelrow">
          <span className="panelrowlabel">Platform signal</span>
          <div className="pillarbtns">
            <button className={`pill ${signalF === "all" ? "on" : ""}`}
                    onClick={() => setSignalF("all")}>
              Any
            </button>
            {COMPETENCIES.map((c) => (
              <button key={c} className={`pill ${signalF === c ? "on" : ""}`}
                      onClick={() => setSignalF(c)}>
                {c}
              </button>
            ))}
          </div>
          <label className="checkrow">
            <input
              type="checkbox"
              checked={showOther}
              onChange={(e) => setShowOther(e.target.checked)}
            />
            Show other activity
          </label>
        </div>
        <div className="panelfoot">
          <span className="count">
            {candidates
              ? `${total} candidates across ${nStates} of the 36 races · showing ${filtered.length}`
              : "Loading…"}
          </span>
        </div>
      </section>

      {rafDevs.length ? (
        <section className="feedcard">
          <div className="feedhead">
            <h3>
              RA-relevant developments
              <span className="feedwindow">
                {windowF === "all" ? " · all time" : ` · last ${windowF} days`}
                {` · ${rafDevs.length}`}
              </span>
            </h3>
          </div>
          <ul className="devlist">
            {rafDevs.map((d) => (
              <DevItem key={d.id} d={d} showWho />
            ))}
          </ul>
        </section>
      ) : devs.length ? (
        <section className="feedcard">
          <div className="feedhead">
            <h3>
              RA-relevant developments
              <span className="feedwindow">
                {windowF === "all" ? " · all time" : ` · last ${windowF} days`}
              </span>
            </h3>
          </div>
          <p className="muted feedempty">
            No RA-relevant developments match the current filters
            {windowF === "all" ? "" : " and window"}.{" "}
            {windowF !== "all" ? (
              <button className="linkbtn" onClick={() => setWindowF("all")}>
                Show all time
              </button>
            ) : null}
          </p>
        </section>
      ) : null}

      <div className="racelist">
        {candidates === null && !error ? <p className="muted">Loading…</p> : null}
        {candidates !== null && !races.length ? (
          <p className="empty">No candidates match the filters.</p>
        ) : null}
        {races.map((r) => (
          <RaceCard
            key={r.state}
            r={r}
            devsByCand={devsByCand}
            recent={statesWithActivity.has(r.state)}
          />
        ))}
      </div>
    </main>
  );
}
