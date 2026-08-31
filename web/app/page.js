"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import usa from "@svg-maps/usa";
import Header from "./header";

const STATE_NAMES = Object.fromEntries(usa.locations.map((l) => [l.id.toUpperCase(), l.name]));

const COMPETENCIES = [
  { key: "civil-service", label: "Civil service", color: "#059669" },
  { key: "procedure", label: "Procedure", color: "#d97706" },
  { key: "digital", label: "Digital", color: "#2563eb" },
  { key: "incentives", label: "Incentives", color: "#7c3aed" },
];
const COMPETENCY_COLOR = Object.fromEntries(COMPETENCIES.map((c) => [c.key, c.color]));

// The four competencies are what's selected by default. Events that fit none of
// them (competency === "none") are hidden unless the "Show other activity" box is on.
const DEFAULT_COMPETENCIES = COMPETENCIES.map((c) => c.key);

// Sector tags describe the policy area (often on "none" events); capacity tags
// describe the machinery. We tint the two differently in the UI.
const SECTOR_TAGS = new Set([
  "data-center", "tax-incentives", "energy-utility", "health-human-services",
  "higher-ed", "k12-education", "child-welfare",
]);

const TIME_WINDOWS = [
  { key: "week", label: "Week", days: 7 },
  { key: "month", label: "Month", days: 31 },
  { key: "all", label: "All", days: null },
];

const PAGE_SIZE = 10;

// e.g. 1 … 4 5 6 … 12 — full list when it's short
function pagesToShow(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const wanted = [...new Set([1, current - 1, current, current + 1, total])]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);
  const out = [];
  let prev = 0;
  for (const p of wanted) {
    if (p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

function cutoffFor(key) {
  const w = TIME_WINDOWS.find((t) => t.key === key);
  if (!w || !w.days) return null;
  const d = new Date();
  d.setDate(d.getDate() - w.days);
  return d.toISOString().slice(0, 10);
}

export default function Home() {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  const [stateFilter, setStateFilter] = useState(null);
  const [competencyFilter, setCompetencyFilter] = useState(() => new Set(DEFAULT_COMPETENCIES));
  const [showOther, setShowOther] = useState(false);
  const [topicFilter, setTopicFilter] = useState("");
  const [activityFilter, setActivityFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [timeFilter, setTimeFilter] = useState("week");
  const [hovered, setHovered] = useState(null);
  const [page, setPage] = useState(1);
  const listRef = useRef(null);

  useEffect(() => {
    setPage(1);
  }, [stateFilter, competencyFilter, showOther, topicFilter, activityFilter, actorFilter, timeFilter]);

  useEffect(() => {
    fetch("/api/events")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setEvents(d.events)))
      .catch((e) => setError(String(e)));
  }, []);

  const activityTypes = useMemo(
    () => [...new Set((events || []).map((e) => e.activity_type).filter(Boolean))].sort(),
    [events]
  );
  const actorTypes = useMemo(
    () => [...new Set((events || []).map((e) => e.actor_type).filter(Boolean))].sort(),
    [events]
  );
  // Topic tags present in the data, most common first (most "interesting" up top).
  const topicTags = useMemo(() => {
    const c = {};
    for (const e of events || []) for (const t of e.topic_tags || []) c[t] = (c[t] || 0) + 1;
    return Object.entries(c)
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([t]) => t);
  }, [events]);

  // Everything except the state filter — drives both map shading and the list
  const baseFiltered = useMemo(() => {
    if (!events) return [];
    const cutoff = cutoffFor(timeFilter);
    return events.filter((e) => {
      if (cutoff && (!e.date || e.date < cutoff)) return false;
      const comps = e.competency || [];
      if (comps.length === 0) {
        if (!showOther) return false;
      } else if (competencyFilter.size && !comps.some((c) => competencyFilter.has(c))) {
        return false;
      }
      if (topicFilter && !(e.topic_tags || []).includes(topicFilter)) return false;
      if (activityFilter && e.activity_type !== activityFilter) return false;
      if (actorFilter && e.actor_type !== actorFilter) return false;
      return true;
    });
  }, [events, competencyFilter, showOther, topicFilter, activityFilter, actorFilter, timeFilter]);

  const countsByState = useMemo(() => {
    const c = {};
    for (const e of baseFiltered) c[e.state] = (c[e.state] || 0) + 1;
    return c;
  }, [baseFiltered]);

  const shown = useMemo(
    () => (stateFilter ? baseFiltered.filter((e) => e.state === stateFilter) : baseFiltered),
    [baseFiltered, stateFilter]
  );

  const totalPages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = shown.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const goTo = (n) => {
    setPage(n);
    listRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const maxCount = Math.max(1, ...Object.values(countsByState));
  const fillFor = (code) => {
    const n = countsByState[code] || 0;
    if (!n) return "#e8edf2";
    const t = n / maxCount;
    const alpha = 0.25 + 0.75 * t;
    return `rgba(37, 99, 235, ${alpha.toFixed(2)})`;
  };

  const toggleCompetency = (key) => {
    const next = new Set(competencyFilter);
    next.has(key) ? next.delete(key) : next.add(key);
    setCompetencyFilter(next);
  };

  const clearAll = () => {
    setStateFilter(null);
    setCompetencyFilter(new Set(DEFAULT_COMPETENCIES));
    setShowOther(false);
    setTopicFilter("");
    setActivityFilter("");
    setActorFilter("");
    setTimeFilter("week");
  };

  const competencyIsDefault =
    !showOther &&
    competencyFilter.size === DEFAULT_COMPETENCIES.length &&
    DEFAULT_COMPETENCIES.every((k) => competencyFilter.has(k));

  const hasFilters =
    stateFilter ||
    !competencyIsDefault ||
    topicFilter ||
    activityFilter ||
    actorFilter ||
    timeFilter !== "week";

  return (
    <main className="wrap">
      <Header active="map" />

      <section className="pagelead">
        <h2 className="pagetitle">State Map</h2>
        <nav className="leadcta" aria-label="Other state views">
          <Link href="/states" className="ctabtn">
            State Profiles
            <span className="ctaarrow" aria-hidden="true">→</span>
          </Link>
          <Link href="/candidates" className="ctabtn">
            Governors &rsquo;26
            <span className="ctaarrow" aria-hidden="true">→</span>
          </Link>
        </nav>
      </section>

      <section className="top">
        <div className="mapcard">
          <svg viewBox={usa.viewBox} role="img" aria-label="US map of events">
            {usa.locations.map((loc) => {
              const code = loc.id.toUpperCase();
              const selected = stateFilter === code;
              return (
                <path
                  key={loc.id}
                  d={loc.path}
                  className={`state ${selected ? "selected" : ""}`}
                  fill={selected ? "#1e3a8a" : fillFor(code)}
                  onClick={() => setStateFilter(selected ? null : code)}
                  onMouseEnter={() => setHovered(code)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <title>{`${loc.name}: ${countsByState[code] || 0} event${(countsByState[code] || 0) === 1 ? "" : "s"}`}</title>
                </path>
              );
            })}
          </svg>
          <div className="maplegend">
            {hovered ? (
              <span>
                <strong>{STATE_NAMES[hovered]}</strong> — {countsByState[hovered] || 0} event
                {(countsByState[hovered] || 0) === 1 ? "" : "s"} · click to filter
              </span>
            ) : (
              <span>Darker = more events · click a state to filter</span>
            )}
          </div>
        </div>

        <aside className="panel">
          <div className="panelrow">
            <label>Time window</label>
            <div className="timebtns">
              {TIME_WINDOWS.map((t) => (
                <button
                  key={t.key}
                  className={`timebtn ${timeFilter === t.key ? "on" : ""}`}
                  onClick={() => setTimeFilter(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="panelrow">
            <label>Competency</label>
            <div className="pillarbtns">
              {COMPETENCIES.map((c) => (
                <button
                  key={c.key}
                  className={`pill ${competencyFilter.has(c.key) ? "on" : ""}`}
                  style={{ "--c": c.color }}
                  onClick={() => toggleCompetency(c.key)}
                >
                  {c.label}
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

          <div className="panelrow">
            <label>Activity type</label>
            <select value={activityFilter} onChange={(e) => setActivityFilter(e.target.value)}>
              <option value="">All</option>
              {activityTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="panelrow">
            <label>Government actor</label>
            <select value={actorFilter} onChange={(e) => setActorFilter(e.target.value)}>
              <option value="">All</option>
              {actorTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="panelrow">
            <label>Topic tag</label>
            <select value={topicFilter} onChange={(e) => setTopicFilter(e.target.value)}>
              <option value="">All</option>
              {topicTags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="panelfoot">
            <span className="count">
              {events ? `${shown.length} event${shown.length === 1 ? "" : "s"}` : "Loading…"}
              {stateFilter ? ` · ${STATE_NAMES[stateFilter] || stateFilter}` : ""}
            </span>
            {hasFilters ? (
              <button className="clear" onClick={clearAll}>
                Reset
              </button>
            ) : null}
          </div>
        </aside>
      </section>

      {error ? <p className="error">Error loading events: {error}</p> : null}

      <section className="list" ref={listRef}>
        {pageItems.map((e) => (
          <article key={e.id} className="card">
            <div className="cardtop">
              <span className="statechip">{e.state}</span>
              <time>{e.date}</time>
              {e.activity_type ? <span className="chip">{e.activity_type}</span> : null}
              {e.actor_type ? <span className="chip actor">{e.actor_type}</span> : null}
              {(e.competency || []).map((c) => (
                <span
                  key={c}
                  className="chip pillar"
                  style={{ "--c": COMPETENCY_COLOR[c] || "#64748b" }}
                >
                  {c}
                </span>
              ))}
              {e.relevance ? (
                <span className="sig" title={`Relevance ${e.relevance}/3`}>
                  {"●".repeat(e.relevance)}
                </span>
              ) : null}
            </div>
            <h2>{e.name.replace(/^[A-Z]{2} — /, "")}</h2>
            {e.notes ? <p className="notes">{e.notes}</p> : null}
            {e.topic_tags?.length ? (
              <div className="tags">
                {e.topic_tags.map((t) => (
                  <button
                    key={t}
                    className={`tag ${SECTOR_TAGS.has(t) ? "sector" : ""} ${
                      topicFilter === t ? "on" : ""
                    }`}
                    onClick={() => setTopicFilter(topicFilter === t ? "" : t)}
                    title="Filter by this tag"
                  >
                    {t}
                  </button>
                ))}
              </div>
            ) : null}
            <div className="cardfoot">
              {e.gov_actor ? <span className="actor-name">{e.gov_actor}</span> : null}
              <span className="links">
                {e.urls.map((u, i) => (
                  <a key={u} href={u} target="_blank" rel="noreferrer">
                    {e.outlets[i] || new URL(u).hostname.replace(/^www\./, "")}
                  </a>
                ))}
              </span>
              {e.article_count > 1 ? <span className="merged">{e.article_count} articles merged</span> : null}
            </div>
          </article>
        ))}
        {events && !shown.length ? <p className="empty">No events match these filters.</p> : null}
      </section>

      {totalPages > 1 ? (
        <nav className="pager" aria-label="Event list pages">
          <button className="pagebtn" disabled={safePage === 1} onClick={() => goTo(safePage - 1)}>
            ← Prev
          </button>
          {pagesToShow(safePage, totalPages).map((p, i) =>
            p === "…" ? (
              <span key={`gap${i}`} className="pagegap">
                …
              </span>
            ) : (
              <button
                key={p}
                className={`pagebtn num ${p === safePage ? "on" : ""}`}
                onClick={() => goTo(p)}
              >
                {p}
              </button>
            )
          )}
          <button
            className="pagebtn"
            disabled={safePage === totalPages}
            onClick={() => goTo(safePage + 1)}
          >
            Next →
          </button>
          <span className="pageinfo">
            {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, shown.length)} of{" "}
            {shown.length}
          </span>
        </nav>
      ) : null}
    </main>
  );
}
