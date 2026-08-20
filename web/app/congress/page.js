"use client";

import { useEffect, useMemo, useState } from "react";
import Header from "../header";
import {
  COMPETENCIES,
  DEFAULT_COMPETENCIES,
  cutoffFor,
  today,
} from "../lib/competencies";

const COMMITTEES = [
  { key: "hsgac", label: "HSGAC", chamber: "senate", full: "Senate Homeland Security & Governmental Affairs" },
  { key: "senate-rules", label: "Senate Rules", chamber: "senate", full: "Senate Rules & Administration" },
  { key: "senate-approps", label: "Senate Approps", chamber: "senate", full: "Senate Appropriations" },
  { key: "house-oversight", label: "House Oversight", chamber: "house", full: "House Oversight & Government Reform" },
  { key: "house-admin", label: "House Admin", chamber: "house", full: "House Administration" },
  { key: "house-rules", label: "House Rules", chamber: "house", full: "House Rules" },
  { key: "house-approps", label: "House Approps", chamber: "house", full: "House Appropriations" },
  { key: "leadership", label: "Leadership", chamber: "house", full: "Chamber leadership (whips)" },
  // GAO moved to the Federal tab on 2026-08-20 — its reports were arriving on
  // both tabs (the trade press covers them heavily) with no cross-tracker
  // dedupe. CBO stays here.
  { key: "cbo", label: "CBO", chamber: "n/a", full: "Congressional Budget Office" },
];

const COMMITTEE_LABEL = Object.fromEntries(COMMITTEES.map((c) => [c.key, c.label]));
const COMMITTEE_FULL = Object.fromEntries(COMMITTEES.map((c) => [c.key, c.full]));

const WINDOWS = [
  { key: "7", label: "7 days", days: 7 },
  { key: "30", label: "30 days", days: 30 },
  { key: "90", label: "90 days", days: 90 },
  { key: "all", label: "All", days: null },
];

// Ordered so the chip reads as progress through the legislative process.
const BILL_STAGES = [
  "introduced",
  "in-committee",
  "reported",
  "passed-chamber",
  "passed-both",
  "enacted",
];

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
  return `${months[Number(m) - 1]} ${Number(d)}, ${y}`;
}

function fmtTime(isoDateTime) {
  if (!isoDateTime || !isoDateTime.includes("T")) return "";
  const t = new Date(isoDateTime);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function CompChips({ values }) {
  if (!values || !values.length) return null;
  return values.map((v) => {
    const c = COMPETENCIES.find((x) => x.key === v);
    return (
      <span key={v} className="compchip" style={{ "--c": c ? c.color : "#94a3b8" }}>
        {c ? c.label : v}
      </span>
    );
  });
}

function Relevance({ value }) {
  if (!value) return null;
  return (
    <span className="sig" title={`Relevance ${value} of 3`}>
      {"•".repeat(value)}
    </span>
  );
}

function Hearing({ h, upcoming }) {
  const [open, setOpen] = useState(false);
  const [showAgenda, setShowAgenda] = useState(false);
  const time = fmtTime(h.hearing_date);
  // A single markup can carry 60+ bills; the full list belongs in the agenda,
  // not in the meta line.
  const billRefs = (h.bill_refs || "").split(",").map((s) => s.trim()).filter(Boolean);
  // Only worth offering the raw agenda when it says more than the title does.
  const rawAgenda = (h.title || "").trim() && h.title.trim() !== (h.short_title || "").trim();

  return (
    <li className={`hearingitem ${upcoming ? "upcoming" : ""}`}>
      <div className="hearingwhen">
        <strong>{fmtDate(h.date)}</strong>
        {time ? <span>{time}</span> : null}
      </div>
      <div className="hearingbody">
        <div className="devmeta">
          <span className="statechip">{COMMITTEE_LABEL[h.committee] || h.committee}</span>
          {h.meeting_type ? <span className="minichip">{h.meeting_type}</span> : null}
          {h.hearing_status && h.hearing_status !== "held" ? (
            <span className={`statuschip ${h.hearing_status}`}>{h.hearing_status}</span>
          ) : null}
          <CompChips values={h.competency} />
          <Relevance value={h.relevance} />
        </div>

        <TitleToggle open={open} onClick={() => setOpen(!open)}>
          {h.short_title}
        </TitleToggle>

        {open ? (
          <div className="itembody">
            {h.agenda_summary ? <p className="itemsummary">{h.agenda_summary}</p> : null}
            {h.why_it_matters ? <p className="whymatters">{h.why_it_matters}</p> : null}
            {h.location ? <p className="itemmeta">{h.location}</p> : null}
            {billRefs.length ? (
              <p className="itemmeta">
                Bills: {billRefs.slice(0, 8).join(", ")}
                {billRefs.length > 8 ? ` +${billRefs.length - 8} more` : ""}
              </p>
            ) : null}

            {h.witnesses.length ? (
              <div className="hearingdetail">
                <span className="detaillabel">Witnesses &amp; statements</span>
                <ul>
                  {h.witnesses.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {h.materials.length ? (
              <div className="hearingdetail">
                <span className="detaillabel">Materials ({h.materials.length})</span>
                <ul>
                  {h.materials.slice(0, 8).map((u, i) => (
                    <li key={i}>
                      <a href={u} target="_blank" rel="noreferrer">
                        {u.replace(/^https?:\/\//, "").slice(0, 70)}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {/* The raw Congress.gov agenda runs to thousands of characters on a
                markup, so it stays behind a second, nested toggle. */}
            {rawAgenda ? (
              <div className="agendatoggle">
                <button className="linkbtn" onClick={() => setShowAgenda(!showAgenda)}>
                  {showAgenda ? "hide full agenda −" : "full agenda +"}
                </button>
                {showAgenda ? <p className="agendafull">{h.title}</p> : null}
              </div>
            ) : null}

            {h.urls[0] ? (
              <a className="sourcelink" href={h.urls[0]} target="_blank" rel="noreferrer">
                View on Congress.gov →
              </a>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

/** Bold short title that toggles the detail block open. */
function TitleToggle({ open, onClick, children }) {
  return (
    <button className="itemtitle" onClick={onClick} aria-expanded={open}>
      <span className="caret">{open ? "▾" : "▸"}</span>
      {children}
    </button>
  );
}

function Bill({ b }) {
  const [open, setOpen] = useState(false);
  const stage = BILL_STAGES.indexOf(b.bill_status);
  return (
    <li className="devitem">
      <div className="devmeta">
        {b.committee_action_date ? <time>{fmtDate(b.committee_action_date)}</time> : null}
        <span className="billnum">{b.bill_number}</span>
        <span className="statechip">{COMMITTEE_LABEL[b.committee] || b.committee}</span>
        {/* What the committee did — the reason this bill is in the list. */}
        {b.committee_action ? (
          <span className={`cmteaction ${b.committee_action}`}>{b.committee_action}</span>
        ) : null}
        {b.bill_status ? (
          <span className={`stagechip s${stage >= 0 ? stage : 0}`}>{b.bill_status}</span>
        ) : null}
        <CompChips values={b.competency} />
        <Relevance value={b.relevance} />
      </div>

      <TitleToggle open={open} onClick={() => setOpen(!open)}>
        {b.title}
      </TitleToggle>

      {open ? (
        <div className="itembody">
          {b.summary ? <p className="itemsummary">{b.summary}</p> : null}
          {b.why_it_matters ? <p className="whymatters">{b.why_it_matters}</p> : null}
          {/* CRS has a summary for only about half of bills, and rarely for the
              substantive recent ones — so it supplements ours, never replaces it. */}
          {b.crs_summary ? (
            <div className="crsblock">
              <span className="crslabel">Congress.gov summary</span>
              <p className="itemsummary">{b.crs_summary}</p>
            </div>
          ) : null}
          <p className="itemmeta">
            {b.sponsor ? <>{b.sponsor}</> : null}
            {b.cosponsor_count ? <> · {b.cosponsor_count} cosponsors</> : null}
            {b.introduced_date ? <> · introduced {fmtDate(b.introduced_date)}</> : null}
          </p>
          {b.latest_action ? <p className="itemmeta">Latest action: {b.latest_action}</p> : null}
          {b.urls[0] ? (
            <a className="sourcelink" href={b.urls[0]} target="_blank" rel="noreferrer">
              View on Congress.gov →
            </a>
          ) : null}
        </div>
      ) : (
        <p className="itemmeta">
          {b.sponsor ? <>{b.sponsor}</> : null}
          {b.latest_action_date ? <> · latest action {fmtDate(b.latest_action_date)}</> : null}
        </p>
      )}
    </li>
  );
}

function ActivityItem({ e }) {
  const [open, setOpen] = useState(false);
  // Rows written before short_title existed fall back to the headline, which
  // is a full sentence — no point offering an expander that repeats it.
  const hasMore = Boolean(
    e.summary || e.why_it_matters || (e.headline && e.headline !== e.short_title)
  );
  return (
    <li className="devitem">
      <div className="devmeta">
        <time>{fmtDate(e.date)}</time>
        <span className="statechip">{COMMITTEE_LABEL[e.committee] || e.committee}</span>
        {/* Only majority/minority carries information. "member" is the default
            for a member's own feed, and "nonpartisan" would repeat on every
            row of the CBO section. */}
        {e.party_source === "majority" || e.party_source === "minority" ? (
          <span className={`partysrc ${e.party_source}`}>{e.party_source}</span>
        ) : null}
        {e.activity_type ? <span className="minichip">{e.activity_type}</span> : null}
        <CompChips values={e.competency} />
        <Relevance value={e.relevance} />
        {e.article_count > 1 ? (
          <span className="devsources">· {e.article_count} sources</span>
        ) : null}
      </div>

      {hasMore ? (
        <TitleToggle open={open} onClick={() => setOpen(!open)}>
          {e.short_title}
        </TitleToggle>
      ) : e.urls[0] ? (
        <a className="devheadline" href={e.urls[0]} target="_blank" rel="noreferrer">
          {e.short_title}
        </a>
      ) : (
        <span className="devheadline">{e.short_title}</span>
      )}

      {open ? (
        <div className="itembody">
          {e.headline && e.headline !== e.short_title ? (
            <p className="itemsummary">{e.headline}</p>
          ) : null}
          {e.summary ? <p className="itemsummary">{e.summary}</p> : null}
          {e.why_it_matters ? <p className="whymatters">{e.why_it_matters}</p> : null}
          {e.topic_tags.length ? (
            <div className="tagrow">
              {e.topic_tags.map((t) => (
                <span key={t} className="minichip">
                  {t}
                </span>
              ))}
            </div>
          ) : null}
          {e.urls[0] ? (
            <a className="sourcelink" href={e.urls[0]} target="_blank" rel="noreferrer">
              Read the source →
            </a>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export default function Congress() {
  const [events, setEvents] = useState(null);
  const [hearings, setHearings] = useState(null);
  const [bills, setBills] = useState(null);
  const [error, setError] = useState("");

  const [compFilter, setCompFilter] = useState(() => new Set(DEFAULT_COMPETENCIES));
  const [showOther, setShowOther] = useState(false);
  const [committeeF, setCommitteeF] = useState("all");
  const [chamberF, setChamberF] = useState("all");
  const [windowF, setWindowF] = useState("30");
  const [watchdogOpen, setWatchdogOpen] = useState(false);

  useEffect(() => {
    const load = (path, set, key) =>
      fetch(path)
        .then((r) => r.json())
        .then((d) => (d.error ? setError(d.error) : set(d[key])))
        .catch((e) => setError(String(e)));
    load("/api/congress", setEvents, "events");
    load("/api/congress-hearings", setHearings, "hearings");
    load("/api/congress-bills", setBills, "bills");
  }, []);

  const cutoff = useMemo(
    () => cutoffFor(WINDOWS.find((w) => w.key === windowF)?.days ?? null),
    [windowF]
  );

  // One predicate for all three sections, so the filter panel means the same
  // thing everywhere. Hearings opt out of the date cutoff — an upcoming
  // hearing is in the future and would fail a "last N days" test.
  const matches = useMemo(() => {
    return (row, { ignoreDate = false } = {}) => {
      const comps = row.competency || [];
      if (comps.length === 0) {
        if (!showOther) return false;
      } else if (!comps.some((c) => compFilter.has(c))) {
        return false;
      }
      if (committeeF !== "all" && row.committee !== committeeF) return false;
      if (chamberF !== "all" && row.chamber !== chamberF) return false;
      if (!ignoreDate && cutoff && (row.date || "") < cutoff) return false;
      return true;
    };
  }, [compFilter, showOther, committeeF, chamberF, cutoff]);

  const now = today();
  const shownHearings = useMemo(
    () => (hearings || []).filter((h) => matches(h, { ignoreDate: true })),
    [hearings, matches]
  );
  const upcoming = shownHearings.filter((h) => (h.date || "") >= now);
  const recentHearings = shownHearings
    .filter((h) => (h.date || "") < now && (!cutoff || (h.date || "") >= cutoff))
    .reverse();

  const shownBills = useMemo(() => (bills || []).filter((b) => matches(b)), [bills, matches]);

  // CBO gets its own section: a nonpartisan support agency rather than a
  // committee. GAO used to share it and dominate it (19 of the first 33 events);
  // GAO now lives on the Federal tab, in its own oversight lane.
  const shownEvents = useMemo(() => (events || []).filter((e) => matches(e)), [events, matches]);
  const isWatchdog = (e) => e.committee === "cbo";
  const committeeEvents = shownEvents.filter((e) => !isWatchdog(e));
  const watchdogEvents = shownEvents.filter(isWatchdog);

  const toggleComp = (key) => {
    const next = new Set(compFilter);
    next.has(key) ? next.delete(key) : next.add(key);
    setCompFilter(next);
  };

  const compIsDefault =
    compFilter.size === DEFAULT_COMPETENCIES.length &&
    DEFAULT_COMPETENCIES.every((k) => compFilter.has(k));
  const hasFilters =
    !compIsDefault || showOther || committeeF !== "all" || chamberF !== "all" || windowF !== "30";

  const clearAll = () => {
    setCompFilter(new Set(DEFAULT_COMPETENCIES));
    setShowOther(false);
    setCommitteeF("all");
    setChamberF("all");
    setWindowF("30");
  };

  const loading = events === null || hearings === null || bills === null;
  const total = shownHearings.length + shownBills.length + shownEvents.length;

  return (
    <main className="wrap">
      <Header active="congress" />

      <p className="tabintro">
        Federal government-capacity activity from the seven committees that govern how
        Washington runs itself, plus CBO. Hearings and bills come from the Congress.gov API;
        committee and member activity is scraped from committee and member press feeds.
        Everything is scored against the same four Recoding America competencies used on the
        state tabs, re-pointed at the federal government. <strong>GAO now lives on the{" "}
        <a href="/federal">Federal</a> tab</strong>, in its own oversight lane, where its
        reports cluster with the trade-press coverage of them.
      </p>

      <section className="panel racepanel congresspanel">
        <div className="panelrow">
          <label>Competency</label>
          <div className="pillarbtns">
            {COMPETENCIES.map((c) => (
              <button
                key={c.key}
                className={`pill ${compFilter.has(c.key) ? "on" : ""}`}
                style={{ "--c": c.color }}
                onClick={() => toggleComp(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>

        <div className="panelrow">
          <label>Committee</label>
          <select value={committeeF} onChange={(e) => setCommitteeF(e.target.value)}>
            <option value="all">All committees</option>
            {COMMITTEES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.full}
              </option>
            ))}
          </select>
        </div>

        <div className="panelrow">
          <label>Chamber</label>
          <div className="pillarbtns">
            {[
              ["all", "All"],
              ["senate", "Senate"],
              ["house", "House"],
              ["n/a", "CBO"],
            ].map(([v, label]) => (
              <button
                key={v}
                className={`pill ${chamberF === v ? "on" : ""}`}
                onClick={() => setChamberF(v)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="panelrow">
          <label>Window</label>
          <div className="timebtns">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                className={`timebtn ${windowF === w.key ? "on" : ""}`}
                onClick={() => setWindowF(w.key)}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>

        <div className="panelrow">
          <label className="checkrow">
            <input
              type="checkbox"
              checked={showOther}
              onChange={(e) => setShowOther(e.target.checked)}
            />
            Show items matching no competency
          </label>
        </div>

        <div className="panelfoot">
          <span className="count">
            {loading
              ? "Loading…"
              : `${upcoming.length} upcoming · ${shownBills.length} bill${
                  shownBills.length === 1 ? "" : "s"
                } · ${committeeEvents.length} committee · ${watchdogEvents.length} CBO`}
          </span>
          {hasFilters ? (
            <button className="clear" onClick={clearAll}>
              Reset
            </button>
          ) : null}
        </div>
      </section>

      {error ? <p className="error">{error}</p> : null}

      {/* ---------- Upcoming hearings & testimony ---------- */}
      <section className="feedcard">
        <div className="feedhead">
          <h3>
            Upcoming hearings &amp; testimony
            <span className="feedwindow"> · {upcoming.length}</span>
          </h3>
        </div>
        {upcoming.length ? (
          <ul className="hearinglist">
            {upcoming.map((h) => (
              <Hearing key={h.id} h={h} upcoming />
            ))}
          </ul>
        ) : (
          <p className="feedempty muted">
            {loading
              ? "Loading…"
              : "Nothing scheduled that matches these filters. Congress schedules most hearings about a week out, and nothing is posted during recess."}
          </p>
        )}

        {recentHearings.length ? (
          <>
            <div className="sectiondivider">
              <span>Recently held</span>
            </div>
            <ul className="hearinglist">
              {recentHearings.map((h) => (
                <Hearing key={h.id} h={h} />
              ))}
            </ul>
          </>
        ) : null}
      </section>

      {/* ---------- Bills ---------- */}
      <section className="feedcard">
        <div className="feedhead">
          <h3>
            Bill activity in these committees
            <span className="feedwindow">
              {windowF === "all" ? " · all time" : ` · last ${windowF} days`} ·{" "}
              {shownBills.length}
            </span>
          </h3>
        </div>
        <p className="sectionnote">
          Bills the seven committees acted on in this window — marked up, reported out, or
          newly referred. Dated by the committee&apos;s action, not the bill&apos;s latest
          floor action, so a bill introduced last year appears when its committee takes it up.
        </p>
        {shownBills.length ? (
          <ul className="devlist">
            {shownBills.map((b) => (
              <Bill key={b.id} b={b} />
            ))}
          </ul>
        ) : (
          <p className="feedempty muted">
            {loading ? "Loading…" : "No bills match these filters."}
            {!loading && !showOther ? (
              <>
                {" "}
                <button className="linkbtn" onClick={() => setShowOther(true)}>
                  Show bills matching no competency
                </button>
              </>
            ) : null}
          </p>
        )}
      </section>

      {/* ---------- Committee & member activity ---------- */}
      <section className="feedcard">
        <div className="feedhead">
          <h3>
            Committee &amp; member activity
            <span className="feedwindow">
              {windowF === "all" ? " · all time" : ` · last ${windowF} days`} ·{" "}
              {committeeEvents.length}
            </span>
          </h3>
        </div>
        {committeeEvents.length ? (
          <ul className="devlist">
            {committeeEvents.map((e) => (
              <ActivityItem key={e.id} e={e} />
            ))}
          </ul>
        ) : (
          <p className="feedempty muted">
            {loading ? "Loading…" : "No committee activity matches these filters."}
            {!loading && windowF !== "all" ? (
              <>
                {" "}
                <button className="linkbtn" onClick={() => setWindowF("all")}>
                  Show all time
                </button>
              </>
            ) : null}
          </p>
        )}
      </section>

      {/* ---------- CBO ----------
          Collapsed by default. This was "GAO & CBO" until GAO moved to the
          Federal tab; CBO alone is low-volume, but it is still a different kind
          of actor from a committee. */}
      <section className="feedcard">
        <div className="feedhead">
          <h3>
            <button
              className="sectiontoggle"
              onClick={() => setWatchdogOpen(!watchdogOpen)}
              aria-expanded={watchdogOpen}
            >
              <span className="caret">{watchdogOpen ? "▾" : "▸"}</span>
              CBO
            </button>
            <span className="feedwindow">
              {windowF === "all" ? " · all time" : ` · last ${windowF} days`} ·{" "}
              {watchdogEvents.length}
            </span>
          </h3>
        </div>
        {watchdogOpen ? (
          <>
            <p className="sectionnote">
              Congress&apos;s nonpartisan scorekeeper. Routine cost estimates are <em>none</em>
              by design; a CBO analysis of an agency&apos;s administrative capacity or
              implementation feasibility is <em>incentives</em>. For GAO, see the{" "}
              <a href="/federal">Federal</a> tab.
            </p>
            {watchdogEvents.length ? (
              <ul className="devlist">
                {watchdogEvents.map((e) => (
                  <ActivityItem key={e.id} e={e} />
                ))}
              </ul>
            ) : (
              <p className="feedempty muted">
                {loading ? "Loading…" : "No CBO items match these filters."}
              </p>
            )}
          </>
        ) : null}
      </section>

      {!loading && total === 0 ? (
        <p className="muted">
          Nothing to show. If this looks wrong rather than quiet, check the per-source funnel:{" "}
          <code>python congress_pipeline.py --days 21 --dry-run</code>
        </p>
      ) : null}
    </main>
  );
}
