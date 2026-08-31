"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import usa from "@svg-maps/usa";
import Header from "../header";
import { LENSES, TABLE_BUCKETS, STATE_COL, COL_LABELS, chipColor, GROUPS } from "./specs-meta";

const STATE_NAMES = Object.fromEntries(usa.locations.map((l) => [l.id.toUpperCase(), l.name]));

function Chip({ v }) {
  if (v === undefined || v === null || v === "") return <span className="dash">—</span>;
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

export default function StatesPage() {
  const router = useRouter();
  const [states, setStates] = useState(null);
  const [error, setError] = useState(null);
  const [lens, setLens] = useState("trifecta");
  const [hovered, setHovered] = useState(null);
  const [filters, setFilters] = useState({}); // colKey -> value (persists across buckets)
  const [sortCol, setSortCol] = useState("postal");
  const [sortDir, setSortDir] = useState(1);
  const [selected, setSelected] = useState([]); // postals for side-by-side
  const [tableBucket, setTableBucket] = useState("basic");

  useEffect(() => {
    fetch("/api/state-specs")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setStates(d.states)))
      .catch((e) => setError(String(e)));
  }, []);

  const byPostal = useMemo(
    () => Object.fromEntries((states || []).map((s) => [s.postal, s])),
    [states]
  );

  const lensCfg = LENSES.find((l) => l.key === lens);
  const fillFor = (code) => {
    const s = byPostal[code];
    if (!s) return "#e8edf2";
    return lensCfg.colors[s[lens]] || "#e8edf2";
  };

  // State column + the columns of the active bucket
  const activeBucket = TABLE_BUCKETS.find((b) => b.key === tableBucket) || TABLE_BUCKETS[0];
  const cols = [STATE_COL, ...activeBucket.cols];

  // distinct values per filterable column (across all buckets), for the dropdowns
  const allCols = useMemo(() => TABLE_BUCKETS.flatMap((b) => b.cols), []);
  const colValues = useMemo(() => {
    const out = {};
    for (const c of allCols) {
      if (!c.filter) continue;
      const vals = new Set();
      for (const s of states || []) {
        const v = s[c.key];
        if (Array.isArray(v)) v.forEach((x) => vals.add(x));
        else if (v) vals.add(v);
      }
      out[c.key] = [...vals].sort();
    }
    return out;
  }, [states, allCols]);

  const rows = useMemo(() => {
    let r = [...(states || [])];
    for (const [k, v] of Object.entries(filters)) {
      if (!v) continue;
      r = r.filter((s) => (Array.isArray(s[k]) ? s[k].includes(v) : s[k] === v));
    }
    r.sort((a, b) => {
      const av = a[sortCol] ?? "";
      const bv = b[sortCol] ?? "";
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * sortDir;
    });
    return r;
  }, [states, filters, sortCol, sortDir]);

  const toggleSort = (k) => {
    if (sortCol === k) setSortDir(-sortDir);
    else {
      setSortCol(k);
      setSortDir(1);
    }
  };

  const toggleSelect = (postal) => {
    setSelected((cur) =>
      cur.includes(postal) ? cur.filter((p) => p !== postal) : cur.length < 4 ? [...cur, postal] : cur
    );
  };

  const anyFilter = Object.values(filters).some(Boolean);

  return (
    <main className="wrap">
      <Header />

      {/* No tab highlights this view any more — it is reached from the State Map
          page — so the page names itself. */}
      <div className="pagelead">
        <h2 className="pagetitle">State Profiles</h2>
      </div>

      <section className="top">
        <div className="mapcard">
          <svg viewBox={usa.viewBox} role="img" aria-label="US map of state profiles">
            {usa.locations.map((loc) => {
              const code = loc.id.toUpperCase();
              const has = !!byPostal[code];
              return (
                <path
                  key={loc.id}
                  d={loc.path}
                  className="state"
                  fill={fillFor(code)}
                  onClick={() => has && router.push(`/states/${code}`)}
                  onMouseEnter={() => setHovered(code)}
                  onMouseLeave={() => setHovered(null)}
                  style={{ cursor: has ? "pointer" : "default" }}
                >
                  <title>{`${loc.name}${has ? ` — ${byPostal[code][lens] || "?"} · click for profile` : ""}`}</title>
                </path>
              );
            })}
          </svg>
          <div className="maplegend">
            {hovered && byPostal[hovered] ? (
              <span>
                <strong>{STATE_NAMES[hovered]}</strong> — {byPostal[hovered][lens] || "—"} · click for
                profile
              </span>
            ) : (
              <span className="leg">
                {lensCfg.legend.map(([name, c]) => (
                  <span key={name} className="legitem">
                    <i style={{ background: c }} /> {name}
                  </span>
                ))}
              </span>
            )}
          </div>
        </div>

        <aside className="panel">
          <div className="panelrow">
            <label>Color map by</label>
            <div className="timebtns">
              {LENSES.map((l) => (
                <button
                  key={l.key}
                  className={`timebtn ${lens === l.key ? "on" : ""}`}
                  onClick={() => setLens(l.key)}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <div className="panelrow">
            <label>Jump to a state</label>
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) window.location.href = `/states/${e.target.value}`;
              }}
            >
              <option value="">Select a state…</option>
              {(states || []).map((s) => (
                <option key={s.postal} value={s.postal}>
                  {s.state}
                </option>
              ))}
            </select>
          </div>

          <div className="panelfoot">
            <span className="count">
              {states ? `${rows.length} of ${states.length} states` : "Loading…"}
            </span>
            {anyFilter ? (
              <button className="clear" onClick={() => setFilters({})}>
                Clear filters
              </button>
            ) : null}
          </div>
        </aside>
      </section>

      {error ? <p className="error">Error loading state specs: {error}</p> : null}

      {selected.length >= 2 ? (
        <section className="sidebyside">
          <div className="sbs-head">
            <h2>Side-by-side ({selected.length})</h2>
            <button className="clear" onClick={() => setSelected([])}>
              Clear
            </button>
          </div>
          <div className="sbs-scroll">
            <table className="sbs-table">
              <thead>
                <tr>
                  <th></th>
                  {selected.map((p) => (
                    <th key={p}>
                      <Link href={`/states/${p}`}>{byPostal[p]?.state || p}</Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {GROUPS.flatMap((g) =>
                  g.fields.map((f) => (
                    <tr key={f.key}>
                      <td className="sbs-label">{f.label}</td>
                      {selected.map((p) => (
                        <td key={p}>
                          {f.plain ? (
                            byPostal[p]?.[f.key] || <span className="dash">—</span>
                          ) : (
                            <Chip v={byPostal[p]?.[f.key]} />
                          )}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="tablecard">
        <div className="buckettabs">
          {TABLE_BUCKETS.map((b) => (
            <button
              key={b.key}
              className={`bucketbtn ${tableBucket === b.key ? "on" : ""}`}
              onClick={() => setTableBucket(b.key)}
            >
              {b.label}
            </button>
          ))}
        </div>

        {anyFilter ? (
          <div className="activefilters">
            <span className="aflabel">Filters:</span>
            {Object.entries(filters)
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <button
                  key={k}
                  className="afchip"
                  onClick={() => setFilters((f) => ({ ...f, [k]: undefined }))}
                  title="Remove filter"
                >
                  {COL_LABELS[k] || k}: <strong>{v}</strong> ✕
                </button>
              ))}
          </div>
        ) : null}

        <div className="tablehint">
          Pick a bucket above to switch columns · click a column to sort · filter with the
          dropdowns (filters stick across buckets, so you can combine them) · check up to 4 states
          to compare side-by-side · click a state for its full profile
        </div>
        <div className="table-scroll">
          <table className="compare">
            <thead>
              <tr>
                <th className="selcol"></th>
                {cols.map((c) => (
                  <th key={c.key}>
                    <button className="sortbtn" onClick={() => toggleSort(c.key)}>
                      {c.label}
                      {sortCol === c.key ? (sortDir === 1 ? " ▲" : " ▼") : ""}
                    </button>
                    {c.filter ? (
                      <select
                        className="colfilter"
                        value={filters[c.key] || ""}
                        onChange={(e) =>
                          setFilters((f) => ({ ...f, [c.key]: e.target.value || undefined }))
                        }
                      >
                        <option value="">all</option>
                        {(colValues[c.key] || []).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    ) : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.postal} className={selected.includes(s.postal) ? "selrow" : ""}>
                  <td className="selcol">
                    <input
                      type="checkbox"
                      checked={selected.includes(s.postal)}
                      onChange={() => toggleSelect(s.postal)}
                      aria-label={`Select ${s.state}`}
                    />
                  </td>
                  {cols.map((c) =>
                    c.key === "postal" ? (
                      <td key={c.key} className="namecell">
                        <Link href={`/states/${s.postal}`}>{s.state}</Link>
                      </td>
                    ) : c.plain ? (
                      <td key={c.key} className="plaincell">
                        {s[c.key] ?? <span className="dash">—</span>}
                      </td>
                    ) : (
                      <td key={c.key}>
                        <Chip v={s[c.key]} />
                      </td>
                    )
                  )}
                </tr>
              ))}
              {states && !rows.length ? (
                <tr>
                  <td colSpan={cols.length + 1} className="empty">
                    No states match these filters.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
