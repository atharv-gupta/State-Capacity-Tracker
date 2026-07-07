"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Header from "../../header";
import { GROUPS, chipColor } from "../specs-meta";

function Value({ field, spec }) {
  const v = spec[field.key];
  if (v === undefined || v === null || v === "") return <span className="dash">—</span>;
  if (field.plain) return <span className="plainval">{v}</span>;
  if (Array.isArray(v)) {
    return (
      <span className="chiprow">
        {v.map((x) => (
          <span key={x} className="spec-chip" style={{ "--c": chipColor(x) }}>
            {x}
          </span>
        ))}
      </span>
    );
  }
  return (
    <span className="spec-chip" style={{ "--c": chipColor(v) }}>
      {v}
    </span>
  );
}

function hostname(u) {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}

export default function StateProfile() {
  const { postal } = useParams();
  const code = String(postal || "").toUpperCase();
  const [states, setStates] = useState(null);
  const [events, setEvents] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/state-specs")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setStates(d.states)))
      .catch((e) => setError(String(e)));
    fetch("/api/events")
      .then((r) => r.json())
      .then((d) => setEvents(d.events || []))
      .catch(() => setEvents([]));
    fetch("/api/candidates")
      .then((r) => r.json())
      .then((d) => setCandidates(d.candidates || []))
      .catch(() => setCandidates([]));
  }, []);

  const spec = useMemo(
    () => (states || []).find((s) => s.postal === code),
    [states, code]
  );

  const raceCands = useMemo(() => {
    const order = {
      incumbent: 0, "primary-winner": 1, "runoff-pending": 2,
      "presumptive-nominee": 3, "major-contender": 4,
    };
    return (candidates || [])
      .filter((c) => c.state === code && c.status !== "withdrawn" && c.status !== "defeated")
      .sort(
        (a, b) =>
          (order[a.status] ?? 9) - (order[b.status] ?? 9) ||
          a.party.localeCompare(b.party) ||
          a.name.localeCompare(b.name)
      );
  }, [candidates, code]);

  const stateEvents = useMemo(
    () =>
      (events || [])
        .filter((e) => e.state === code)
        .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
        .slice(0, 5),
    [events, code]
  );

  return (
    <main className="wrap">
      <Header active="states" />

      <div className="crumbs">
        <Link href="/states">← All states</Link>
      </div>

      {error ? <p className="error">Error: {error}</p> : null}
      {states && !spec ? <p className="empty">No profile for “{code}”.</p> : null}

      {spec ? (
        <>
          <div className="profilehead">
            <h2>{spec.state}</h2>
            <span className="statechip">{spec.postal}</span>
          </div>

          {/* Live news feed for this state, joined on postal */}
          <section className="feedcard">
            <div className="feedhead">
              <h3>Recent activity</h3>
              <Link href="/" className="feedlink">
                full feed →
              </Link>
            </div>
            {events === null ? (
              <p className="muted">Loading feed…</p>
            ) : stateEvents.length ? (
              <ul className="feedlist">
                {stateEvents.map((e) => (
                  <li key={e.id}>
                    <time>{e.date}</time>
                    <span className="feedname">{e.name.replace(/^[A-Z]{2} — /, "")}</span>
                    {(e.competency || []).map((c) => (
                      <span key={c} className="minichip">
                        {c}
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No recent tracked events for this state.</p>
            )}
          </section>

          {/* 2026 governor's race, joined on postal */}
          {raceCands.length ? (
            <section className="feedcard">
              <div className="feedhead">
                <h3>2026 governor&rsquo;s race</h3>
                <Link href="/candidates" className="feedlink">
                  all races →
                </Link>
              </div>
              <div className="racehead" style={{ border: "none", margin: 0, paddingBottom: 4 }}>
                {raceCands[0].race_rating ? (
                  <span className="ratingchip lean">{raceCands[0].race_rating}</span>
                ) : null}
                {raceCands[0].race_type === "open" ? (
                  <span className="openchip">open seat</span>
                ) : null}
                {raceCands[0].primary_date ? (
                  <span className="primaryinfo">
                    primary {raceCands[0].primary_date}
                    {raceCands[0].primary_held ? " ✓" : ""}
                  </span>
                ) : null}
              </div>
              <div className="candlist">
                {raceCands.map((c) => (
                  <div className="candrow" key={c.id}>
                    <div className="candtop">
                      <span className="partychip" style={{ "--pc": c.party === "R" ? "#b3453c" : c.party === "D" ? "#3c6cb3" : "#8a7a4a" }}>
                        {c.party}
                      </span>
                      <span className="candname">{c.name}</span>
                      {c.role ? <span className="candrole">{c.role}</span> : null}
                      <span className={`candstatus s-${c.status}`}>
                        {c.status.replace(/-/g, " ")}
                      </span>
                      {(c.competency_signals || []).map((s) => (
                        <span key={s} className="minichip">{s}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {/* Four spec sections */}
          <div className="specgrid">
            {GROUPS.map((g) => {
              const src = spec[g.source];
              const asof = spec[g.asof];
              const visible = g.fields.filter(
                (f) => spec[f.key] !== undefined && spec[f.key] !== "" && spec[f.key] !== null
              );
              const notes = g.notes.filter((n) => spec[n.key]);
              return (
                <section key={g.key} className="speccard">
                  <div className="speccardhead" style={{ "--c": g.color }}>
                    <h3>{g.title}</h3>
                    <span className="prov">
                      {src ? (
                        <a href={src} target="_blank" rel="noreferrer">
                          {hostname(src)}
                        </a>
                      ) : null}
                      {asof ? <span className="asof">as of {asof}</span> : null}
                    </span>
                  </div>
                  <dl className="specdl">
                    {visible.map((f) => (
                      <div className="specrow" key={f.key}>
                        <dt>{f.label}</dt>
                        <dd>
                          <Value field={f} spec={spec} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {notes.length ? (
                    <div className="specnotes">
                      {notes.map((n) => (
                        <p key={n.key}>
                          <span className="notelabel">{n.label}:</span> {spec[n.key]}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {!visible.length && !notes.length ? (
                    <p className="muted">No data loaded yet.</p>
                  ) : null}
                </section>
              );
            })}
          </div>
        </>
      ) : !states && !error ? (
        <p className="muted">Loading…</p>
      ) : null}
    </main>
  );
}
