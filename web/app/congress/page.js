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
  { key: "gao", label: "GAO", chamber: "n/a", full: "Government Accountability Office" },
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

/**
 * Congress.gov hearing "titles" are the full agenda — a business meeting can
 * run 1,500+ characters listing every bill and post-office naming. Cut to the
 * first clause for display; the LLM agenda summary carries the substance and
 * the full text sits behind the expand toggle.
 */
function shortTitle(title, max = 130) {
  const t = (title || "").replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  const head = t.slice(0, max);
  const cut = Math.max(head.lastIndexOf(", "), head.lastIndexOf("; "));
  return `${(cut > 60 ? head.slice(0, cut) : head).trim()}…`;
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
  const time = fmtTime(h.hearing_date);
  const display = shortTitle(h.title);
  const truncated = display !== (h.title || "").replace(/\s+/g, " ").trim();
  const extras = h.witnesses.length + h.materials.length + (truncated ? 1 : 0);
  // A single markup can carry 60+ bills; the full list belongs in the agenda,
  // not in the meta line.
  const billRefs = (h.bill_refs || "").split(",").map((s) => s.trim()).filter(Boolean);
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
        {h.urls[0] ? (
          <a
            className="devheadline"
            href={h.urls[0]}
            target="_blank"
            rel="noreferrer"
            title={h.title}
          >
            {display}
          </a>
        ) : (
          <span className="devheadline" title={h.title}>
            {display}
          </span>
        )}
        {h.agenda_summary ? <p className="itemsummary">{h.agenda_summary}</p> : null}
        {h.location ? <p className="itemmeta">{h.location}</p> : null}
        {billRefs.length ? (
          <p className="itemmeta">
            Bills: {billRefs.slice(0, 8).join(", ")}
            {billRefs.length > 8 ? ` +${billRefs.length - 8} more` : ""}
          </p>
        ) : null}
        {extras ? (
          <button className="linkbtn" onClick={() => setOpen(!open)}>
            {open ? "less −" : `full agenda, witnesses & materials +(${extras})`}
          </button>
        ) : null}
        {open ? (
          <div className="hearingdetail">
            {truncated ? (
              <>
                <span className="detaillabel">Full agenda</span>
                <p className="agendafull">{h.title}</p>
              </>
            ) : null}
            {h.witnesses.length ? (
              <>
                <span className="detaillabel">Witnesses & statements</span>
                <ul>{h.witnesses.map((w, i) => <li key={i}>{w}</li>)}</ul>
              </>
            ) : null}
            {h.materials.length ? (
              <>
                <span className="detaillabel">Materials</span>
                <ul>
                  {h.materials.map((u, i) => (
                    <li key={i}>
                      <a href={u} target="_blank" rel="noreferrer">
                        {u.replace(/^https?:\/\//, "").slice(0, 70)}
                      </a>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function Bill({ b }) {
  const stage = BILL_STAGES.indexOf(b.bill_status);
  return (
    <li className="devitem">
      <div className="devmeta">
        <span className="billnum">{b.bill_number}</span>
        <span className="statechip">{COMMITTEE_LABEL[b.committee] || b.committee}</span>
        {b.bill_status ? (
          <span className={`stagechip s${stage >= 0 ? stage : 0}`}>{b.bill_status}</span>
        ) : null}
        <CompChips values={b.competency} />
        <Relevance value={b.relevance} />
      </div>
      {b.urls[0] ? (
        <a className="devheadline" href={b.urls[0]} target="_blank" rel="noreferrer">
          {b.title}
        </a>
      ) : (
        <span className="devheadline">{b.title}</span>
      )}
      {b.summary ? <p className="itemsummary">{b.summary}</p> : null}
      <p className="itemmeta">
        {b.sponsor ? <>{b.sponsor}</> : null}
        {b.cosponsor_count ? <> · {b.cosponsor_count} cosponsors</> : null}
        {b.latest_action_date ? <> · latest action {fmtDate(b.latest_action_date)}</> : null}
      </p>
    </li>
  );
}

function ActivityItem({ e }) {
  return (
    <li className="devitem">
      <div className="devmeta">
        <time>{fmtDate(e.date)}</time>
        <span className="statechip">{COMMITTEE_LABEL[e.committee] || e.committee}</span>
        {e.party_source && e.party_source !== "member" ? (
          <span className={`partysrc ${e.party_source}`}>{e.party_source}</span>
        ) : null}
        {e.activity_type ? <span className="minichip">{e.activity_type}</span> : null}
        <CompChips values={e.competency} />
        <Relevance value={e.relevance} />
        {e.article_count > 1 ? (
          <span className="devsources">· {e.article_count} sources</span>
        ) : null}
      </div>
      {e.urls[0] ? (
        <a className="devheadline" href={e.urls[0]} target="_blank" rel="noreferrer">
          {e.headline}
        </a>
      ) : (
        <span className="devheadline">{e.headline}</span>
      )}
      {e.summary ? <p className="itemsummary">{e.summary}</p> : null}
      {e.why_it_matters ? <p className="whymatters">{e.why_it_matters}</p> : null}
      {e.topic_tags.length ? (
        <div className="tagrow">
          {e.topic_tags.map((t) => (
            <span key={t} className="minichip">{t}</span>
          ))}
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
  const shownEvents = useMemo(() => (events || []).filter((e) => matches(e)), [events, matches]);

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
        Washington runs itself &mdash; plus GAO and CBO. Hearings and bills come from the
        Congress.gov API; committee and member activity is scraped from committee and member
        press feeds. Everything is scored against the same four RAF competencies used on the
        state tabs, re-pointed at the federal government.
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
              ["n/a", "GAO / CBO"],
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
                } · ${shownEvents.length} event${shownEvents.length === 1 ? "" : "s"}`}
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
            Bills before these committees
            <span className="feedwindow"> · {shownBills.length}</span>
          </h3>
        </div>
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
              {shownEvents.length}
            </span>
          </h3>
        </div>
        {shownEvents.length ? (
          <ul className="devlist">
            {shownEvents.map((e) => (
              <ActivityItem key={e.id} e={e} />
            ))}
          </ul>
        ) : (
          <p className="feedempty muted">
            {loading ? "Loading…" : "No activity matches these filters."}
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

      {!loading && total === 0 ? (
        <p className="muted">
          Nothing to show. If this looks wrong rather than quiet, check the per-source funnel:{" "}
          <code>python congress_pipeline.py --days 21 --dry-run</code>
        </p>
      ) : null}
    </main>
  );
}
