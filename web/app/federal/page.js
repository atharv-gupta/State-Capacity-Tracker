"use client";

import { useEffect, useMemo, useState } from "react";
import Header from "../header";
import { COMPETENCIES, DEFAULT_COMPETENCIES, cutoffFor } from "../lib/competencies";

/**
 * Federal tab — the executive branch, the watchdogs auditing it, and the trade
 * press that covers both.
 *
 * Deliberately split from the Congress tab rather than merged into it. The
 * Congress tab is primary-source and committee-shaped: hearings, bills, and
 * committee press, organised by who has jurisdiction. This tab is
 * instrument-shaped: what the executive branch did, what the press reported
 * about it, and what landed in the Federal Register. A reader looking for
 * "what happened to the federal workforce this week" comes here; a reader
 * looking for "what is HSGAC doing" goes there.
 *
 * Four lanes, in descending order of provenance, because that is the order a
 * reader should trust them in. GAO moved here from the Congress tab on
 * 2026-08-20: the trade press covers its reports heavily, so they were landing
 * on this tab anyway with nothing to deduplicate them against the Congress tab's
 * copy. Its own lane rather than "executive actions" because GAO is a
 * legislative-branch auditor, and because at ~24 reports per three weeks it
 * outweighs everything else here and has to be collapsible.
 */

const LANES = [
  {
    key: "executive-action",
    title: "Executive actions",
    note:
      "Agency primary sources — OMB memoranda and circulars, OPM and GSA instruments, " +
      "executive orders. What the executive branch did, in its own words, with the " +
      "promotional language stripped out. An item is here only if a concrete instrument " +
      "can be named.",
    collapsible: false,
  },
  {
    key: "oversight",
    title: "Oversight & watchdog",
    note:
      "GAO. Reports on whether federal programs, systems and workforces actually " +
      "work — which is the incentives competency almost by construction, so this " +
      "lane runs at higher volume than the rest of the tab combined. A report and " +
      "the trade-press coverage of it are one row here. CBO stays on the Congress " +
      "tab, where a cost estimate belongs.",
    collapsible: true,
  },
  {
    key: "news",
    title: "Federal news",
    note:
      "FedScoop, Government Executive, Nextgov/FCW, Federal News Network, MeriTalk and " +
      "The Hill. Second-hand, but the only lane that catches an action no agency " +
      "announced — a draft memo, an internal directive, a RIF in progress. Items are " +
      "labelled where the action is reported rather than published.",
    collapsible: false,
  },
  {
    key: "rulemaking",
    title: "Rulemaking & notices",
    note:
      "The Federal Register: proposed and final rules, notices with legal effect, and " +
      "presidential documents. Scoped to the agencies that run the machinery of " +
      "government, every presidential document, and a capacity-vocabulary sweep across " +
      "all agencies — the full Register is ~1,600 documents every three weeks, almost " +
      "all of it ordinary regulatory business.",
    collapsible: true,
  },
];

// The four we scrape directly lead the filter; the rest appear only when the
// window actually contains them, so the dropdown stays short.
const AGENCY_LABELS = {
  opm: "OPM",
  omb: "OMB",
  gsa: "GSA",
  "white-house": "White House",
  governmentwide: "Governmentwide",
  gao: "GAO",
  mspb: "MSPB",
  flra: "FLRA",
  oge: "OGE",
  nara: "NARA",
  oira: "OIRA",
  dod: "DoD",
  va: "VA",
  ssa: "SSA",
  hhs: "HHS",
  cms: "CMS",
  irs: "IRS",
  treasury: "Treasury",
  dhs: "DHS",
  cisa: "CISA",
  fema: "FEMA",
  tsa: "TSA",
  "cbp-ice": "CBP / ICE",
  state: "State",
  doj: "DOJ",
  ed: "Education",
  dol: "Labor",
  doi: "Interior",
  usda: "USDA",
  doe: "Energy",
  epa: "EPA",
  hud: "HUD",
  dot: "Transportation",
  faa: "FAA",
  sba: "SBA",
  nasa: "NASA",
  nsf: "NSF",
  commerce: "Commerce",
  nist: "NIST",
  census: "Census",
  eac: "EAC",
  fcc: "FCC",
  ftc: "FTC",
  sec: "SEC",
  nrc: "NRC",
  usaid: "USAID",
  usps: "USPS",
  courts: "Federal courts",
  other: "Other",
};

const LEAD_AGENCIES = ["opm", "omb", "gsa", "white-house", "governmentwide"];

const WINDOWS = [
  { key: "7", label: "7 days", days: 7 },
  { key: "30", label: "30 days", days: 30 },
  { key: "90", label: "90 days", days: 90 },
  { key: "all", label: "All", days: null },
];

const BRANCHES = [
  ["all", "All"],
  ["executive", "Executive"],
  ["congress", "Congress"],
  ["judiciary", "Courts"],
];

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  const months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
  return `${months[Number(m) - 1]} ${Number(d)}, ${y}`;
}

function agencyLabel(key) {
  return AGENCY_LABELS[key] || key;
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

/** Bold short title that toggles the detail block open. */
function TitleToggle({ open, onClick, children }) {
  return (
    <button className="itemtitle" onClick={onClick} aria-expanded={open}>
      <span className="caret">{open ? "▾" : "▸"}</span>
      {children}
    </button>
  );
}

/**
 * Links out of an expanded event.
 *
 * A clustered event usually holds the instrument AND the reporting on it — the
 * Federal Register rule and the Federal News Network story about it, the GAO
 * report and the FedScoop write-up. Showing only the first URL hid whichever
 * one lost the sort, so this offers one link of each kind, labelled by
 * publisher, and names the rest without linking them.
 */
function SourceLinks({ e }) {
  const sources = e.sources || [];
  const primary = sources.filter((s) => s.kind === "primary");
  // Any press outlet will do when several covered the same action; they are
  // near-interchangeable for checking an agency's framing against a reporter's.
  const press = sources.filter((s) => s.kind === "press");
  const shown = [primary[0], press[0]].filter(Boolean);
  // Where the cluster is all one kind (a rule plus the agency's own release, or
  // three trade write-ups and no primary document), still offer a second link.
  if (shown.length === 1) {
    const pool = primary.length > 1 ? primary : press;
    if (pool[1]) shown.push(pool[1]);
  }
  // A document the sources only point at — an OMB memo PDF behind a news story.
  const extraDoc =
    e.document_url && !sources.some((s) => s.url === e.document_url) ? e.document_url : null;
  const rest = sources.filter((s) => !shown.includes(s));

  if (!shown.length && !extraDoc) return null;
  return (
    <>
      <div className="sourcelinks">
        {extraDoc ? (
          <a className="sourcelink" href={extraDoc} target="_blank" rel="noreferrer">
            Primary document →
          </a>
        ) : null}
        {shown.map((s) => (
          <a
            key={s.url}
            className="sourcelink"
            href={s.url}
            target="_blank"
            rel="noreferrer"
            title={s.kind === "primary" ? "Government primary source" : "Press coverage"}
          >
            {s.outlet} →
          </a>
        ))}
      </div>
      {rest.length ? (
        <p className="itemmeta">
          Also: {[...new Set(rest.map((s) => s.outlet))].join(", ")}
        </p>
      ) : null}
    </>
  );
}

function ActionItem({ e }) {
  const [open, setOpen] = useState(false);
  const hasMore = Boolean(
    e.summary || e.why_it_matters || (e.headline && e.headline !== e.short_title)
  );
  return (
    <li className="devitem">
      <div className="devmeta">
        <time>{fmtDate(e.date)}</time>
        {/* Up to two agencies: a governmentwide OMB memo naming five agencies
            would otherwise fill the row with chips. */}
        {(e.agency || []).slice(0, 2).map((a) => (
          <span key={a} className="statechip">
            {agencyLabel(a)}
          </span>
        ))}
        {(e.agency || []).length > 2 ? (
          <span className="devsources">+{e.agency.length - 2}</span>
        ) : null}
        {e.branch && e.branch !== "executive" ? (
          <span className={`branchchip ${e.branch}`}>{e.branch}</span>
        ) : null}
        {e.instrument_type ? <span className="minichip">{e.instrument_type}</span> : null}
        {e.instrument_id ? <span className="billnum">{e.instrument_id}</span> : null}
        {/* `official` is the default and would repeat on every primary-source row. */}
        {e.verification && e.verification !== "official" ? (
          <span className={`verifchip ${e.verification}`}>{e.verification}</span>
        ) : null}
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
          {e.actor || e.status ? (
            <p className="itemmeta">
              {e.actor}
              {e.actor && e.status ? " · " : ""}
              {e.status}
            </p>
          ) : null}
          {e.topic_tags.length ? (
            <div className="tagrow">
              {e.topic_tags.map((t) => (
                <span key={t} className="minichip">
                  {t}
                </span>
              ))}
            </div>
          ) : null}
          <SourceLinks e={e} />
        </div>
      ) : null}
    </li>
  );
}

export default function Federal() {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState("");

  const [compFilter, setCompFilter] = useState(() => new Set(DEFAULT_COMPETENCIES));
  const [showOther, setShowOther] = useState(false);
  const [agencyF, setAgencyF] = useState("all");
  const [branchF, setBranchF] = useState("all");
  const [windowF, setWindowF] = useState("30");
  const [officialOnly, setOfficialOnly] = useState(false);
  // Collapsible lanes start closed; two of the four are high-volume.
  const [openLanes, setOpenLanes] = useState(() => new Set());
  const toggleLane = (key) =>
    setOpenLanes((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  useEffect(() => {
    fetch("/api/federal")
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setEvents(d.events)))
      .catch((e) => setError(String(e)));
  }, []);

  const cutoff = useMemo(
    () => cutoffFor(WINDOWS.find((w) => w.key === windowF)?.days ?? null),
    [windowF]
  );

  const matches = useMemo(() => {
    return (row) => {
      const comps = row.competency || [];
      if (comps.length === 0) {
        if (!showOther) return false;
      } else if (!comps.some((c) => compFilter.has(c))) {
        return false;
      }
      if (agencyF !== "all" && !(row.agency || []).includes(agencyF)) return false;
      if (branchF !== "all" && row.branch !== branchF) return false;
      if (officialOnly && row.verification !== "official") return false;
      if (cutoff && (row.date || "") < cutoff) return false;
      return true;
    };
  }, [compFilter, showOther, agencyF, branchF, officialOnly, cutoff]);

  const shown = useMemo(() => (events || []).filter(matches), [events, matches]);
  const byLane = useMemo(() => {
    const out = { "executive-action": [], oversight: [], news: [], rulemaking: [] };
    for (const e of shown) (out[e.lane] || out.news).push(e);
    return out;
  }, [shown]);

  // Only offer agencies that appear in the data, so the dropdown reflects the
  // window rather than the full 49-agency vocabulary.
  const agencyOptions = useMemo(() => {
    const present = new Set();
    for (const e of events || []) for (const a of e.agency || []) present.add(a);
    const lead = LEAD_AGENCIES.filter((a) => present.has(a));
    const rest = [...present]
      .filter((a) => !LEAD_AGENCIES.includes(a))
      .sort((a, b) => agencyLabel(a).localeCompare(agencyLabel(b)));
    return [...lead, ...rest];
  }, [events]);

  const toggleComp = (key) => {
    const next = new Set(compFilter);
    next.has(key) ? next.delete(key) : next.add(key);
    setCompFilter(next);
  };

  const compIsDefault =
    compFilter.size === DEFAULT_COMPETENCIES.length &&
    DEFAULT_COMPETENCIES.every((k) => compFilter.has(k));
  const hasFilters =
    !compIsDefault ||
    showOther ||
    agencyF !== "all" ||
    branchF !== "all" ||
    officialOnly ||
    windowF !== "30";

  const clearAll = () => {
    setCompFilter(new Set(DEFAULT_COMPETENCIES));
    setShowOther(false);
    setAgencyF("all");
    setBranchF("all");
    setOfficialOnly(false);
    setWindowF("30");
  };

  const loading = events === null;

  return (
    <main className="wrap">
      <Header active="federal" />

      <p className="tabintro">
        What the <strong>federal executive branch</strong> is doing to itself, scored against the
        same four Recoding America competencies as the state tabs. Four lanes in descending
        order of provenance: agency instruments, GAO&apos;s audits of them, the trade press
        that covers both, and the Federal Register. Agency press offices publish to be quoted, so an item enters only
        when a concrete instrument can be named &mdash; a memo, a rule, a directive, a
        workforce or procurement action, a launch, a reorganisation, a finding, a court order.
        Framing alone is not an event. For committee activity, hearings and bills, see the{" "}
        <a href="/congress">Congress</a> tab; Hill coverage that appears here is labelled.
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
          <label>Agency</label>
          <select value={agencyF} onChange={(e) => setAgencyF(e.target.value)}>
            <option value="all">All agencies</option>
            {agencyOptions.map((a) => (
              <option key={a} value={a}>
                {agencyLabel(a)}
              </option>
            ))}
          </select>
        </div>

        <div className="panelrow">
          <label>Branch</label>
          <div className="pillarbtns">
            {BRANCHES.map(([v, label]) => (
              <button
                key={v}
                className={`pill ${branchF === v ? "on" : ""}`}
                onClick={() => setBranchF(v)}
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
              checked={officialOnly}
              onChange={(e) => setOfficialOnly(e.target.checked)}
            />
            Published instruments only (hide reported and draft)
          </label>
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
              : `${byLane["executive-action"].length} executive · ` +
                `${byLane.oversight.length} oversight · ${byLane.news.length} news · ` +
                `${byLane.rulemaking.length} rulemaking`}
          </span>
          {hasFilters ? (
            <button className="clear" onClick={clearAll}>
              Reset
            </button>
          ) : null}
        </div>
      </section>

      {error ? <p className="error">{error}</p> : null}

      {LANES.map((lane) => {
        const rows = byLane[lane.key];
        const open = !lane.collapsible || openLanes.has(lane.key);
        return (
          <section className="feedcard" key={lane.key}>
            <div className="feedhead">
              <h3>
                {lane.collapsible ? (
                  <button
                    className="sectiontoggle"
                    onClick={() => toggleLane(lane.key)}
                    aria-expanded={open}
                  >
                    <span className="caret">{open ? "▾" : "▸"}</span>
                    {lane.title}
                  </button>
                ) : (
                  lane.title
                )}
                <span className="feedwindow">
                  {windowF === "all" ? " · all time" : ` · last ${windowF} days`} · {rows.length}
                </span>
              </h3>
            </div>
            {open ? (
              <>
                <p className="sectionnote">{lane.note}</p>
                {rows.length ? (
                  <ul className="devlist">
                    {rows.map((e) => (
                      <ActionItem key={e.id} e={e} />
                    ))}
                  </ul>
                ) : (
                  <p className="feedempty muted">
                    {loading ? "Loading…" : "Nothing in this lane matches these filters."}
                    {!loading && !showOther ? (
                      <>
                        {" "}
                        <button className="linkbtn" onClick={() => setShowOther(true)}>
                          Show items matching no competency
                        </button>
                      </>
                    ) : null}
                  </p>
                )}
              </>
            ) : null}
          </section>
        );
      })}

      {!loading && shown.length === 0 ? (
        <p className="muted">
          Nothing to show. If this looks wrong rather than quiet, check the per-source funnel:{" "}
          <code>python federal_pipeline.py --days 21 --dry-run</code>
        </p>
      ) : null}
    </main>
  );
}
