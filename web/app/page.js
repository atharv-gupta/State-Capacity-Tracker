"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { warm } from "./lib/datacache";

/**
 * Landing page.
 *
 * Three jobs, in this order: get the reader subscribed, get them into the right
 * tab, and stay out of the way. Everything here serves one of those; there is
 * no fourth section.
 *
 * The staged reveal is not decoration. Every tab fetches its whole Airtable
 * table on mount, and a cold click used to land on an empty page for the length
 * of that round-trip. This page starts those fetches on mount (`warm`) and
 * spends the wait introducing itself, so the reader is reading while the data
 * arrives. The counters are the honest end of that: they sit as a placeholder
 * dash until the real numbers land, then count up to them. Nothing here fakes
 * progress it does not have.
 */

const DOORS = [
  {
    href: "/states",
    key: "states",
    n: "01",
    label: "States",
    color: "#2563eb",
    blurb:
      "Fifty legislatures, governors and agencies — mapped, filtered, and tagged by what part of the machinery they touch.",
    api: "/api/events",
  },
  {
    href: "/congress",
    key: "congress",
    n: "02",
    label: "Congress",
    color: "#7c3aed",
    blurb:
      "Committee actions, hearings and bills that change how the federal government runs itself, plus what's on the calendar.",
    api: "/api/congress",
  },
  {
    href: "/federal",
    key: "federal",
    n: "03",
    label: "Federal",
    color: "#059669",
    blurb:
      "OMB memos, OPM rules, executive orders and watchdog findings — the executive branch acting on its own capacity.",
    api: "/api/federal",
  },
];

const LENSES = [
  {
    label: "Civil service",
    color: "#059669",
    what: "Who government hires and how it manages them.",
  },
  {
    label: "Procedure",
    color: "#d97706",
    what: "The process and paperwork government imposes on itself.",
  },
  {
    label: "Digital",
    color: "#2563eb",
    what: "The technology and data it builds, buys, and oversees.",
  },
  {
    label: "Incentives",
    color: "#7c3aed",
    what: "How government checks what worked.",
  },
];

// Endpoints a destination tab needs that no counter reads. The Congress tab
// renders from three tables, not one, so warming only the one behind its count
// would leave two thirds of that page still waiting on the click.
const EXTRA_WARM = ["/api/congress-hearings", "/api/congress-bills"];

/** Count up to `value` once it is known. Instant when the reader prefers that. */
function Counter({ value }) {
  const [shown, setShown] = useState(0);
  const frame = useRef(0);

  useEffect(() => {
    if (value == null) return undefined;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setShown(value);
      return undefined;
    }
    const start = performance.now();
    const DURATION = 900;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / DURATION);
      // ease-out cubic: fast first, settles on the real number
      setShown(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [value]);

  if (value == null) return <span className="statnum pending">—</span>;
  return <span className="statnum">{shown.toLocaleString()}</span>;
}

export default function Home() {
  const router = useRouter();
  const [counts, setCounts] = useState({});
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState(""); // honeypot — see /api/subscribe
  const [status, setStatus] = useState({ state: "idle" });

  // Warm the routes and the data behind them while the hero is being read, then
  // count what the tracker actually tracks: an event matching none of the four
  // competencies is a row we read and set aside, not a finding. A warm that
  // fails resolves to null and simply leaves that counter showing its dash.
  useEffect(() => {
    DOORS.forEach((d) => router.prefetch(d.href));
    warm(EXTRA_WARM);
    warm(DOORS.map((d) => d.api)).then((payloads) => {
      const next = {};
      payloads.forEach((p, i) => {
        if (p && !p.error && Array.isArray(p.events)) {
          next[DOORS[i].key] = p.events.filter(
            (e) => (e.competency || []).length > 0
          ).length;
        }
      });
      setCounts(next);
    });
  }, [router]);

  async function subscribe(e) {
    e.preventDefault();
    if (status.state === "sending") return;
    setStatus({ state: "sending" });
    try {
      const res = await fetch("/api/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, company }),
      });
      const d = await res.json();
      if (!res.ok || d.error) {
        setStatus({ state: "error", message: d.error || "Something went wrong." });
        return;
      }
      setStatus({
        state: "done",
        message: d.already
          ? "You're already on the list — nothing to do."
          : d.resubscribed
            ? "Welcome back. You're on the list again."
            : "You're on the list. The next digest goes out Monday.",
      });
      setEmail("");
    } catch {
      setStatus({ state: "error", message: "Couldn't reach the server. Try again." });
    }
  }

  return (
    <main className="home">
      <section className="hero">
        <div className="herowrap">
         <div className="herogrid">
          <div className="heromain">
          <div className="rule" aria-hidden="true">
            <i style={{ "--c": "#059669", "--i": 0 }} />
            <i style={{ "--c": "#d97706", "--i": 1 }} />
            <i style={{ "--c": "#2563eb", "--i": 2 }} />
            <i style={{ "--c": "#7c3aed", "--i": 3 }} />
          </div>

          <h1 className="herotitle">
            <span style={{ "--i": 0 }}>State Capacity</span>{" "}
            <span style={{ "--i": 1 }}>News Tracker</span>
          </h1>

          <p className="herotag" style={{ "--i": 2 }}>
            Follow along with what governments are doing in the world of state capacity.
          </p>

          <p className="heroblurb" style={{ "--i": 3 }}>
            Not policy news. This tracks the machinery underneath it — how governments hire,
            what procedure they impose on themselves, the technology they build and buy, and
            whether anyone checks if it worked.
          </p>

          <div className="herocta" style={{ "--i": 4 }}>
            <a href="#subscribe" className="hbtn primary">
              Get the weekly digest
            </a>
            <Link href="/states" className="hbtn ghost">
              Browse the tracker
            </Link>
          </div>
          </div>

          {/* The four competencies, in the four colours they carry on every
              tab. Here because "state capacity" is an abstraction until you
              see what counts as one, and the reader meets these as filters
              thirty seconds later. */}
          <aside className="herolens" style={{ "--i": 5 }}>
            <h2>What counts as capacity</h2>
            <ul>
              {LENSES.map((l) => (
                <li key={l.label} style={{ "--c": l.color }}>
                  <b>{l.label}</b>
                  <span>{l.what}</span>
                </li>
              ))}
            </ul>
          </aside>
         </div>
        </div>
      </section>

      <div className="homewrap">
        <nav className="doors" aria-label="Tracker sections">
          {DOORS.map((d, i) => (
            <Link
              key={d.key}
              href={d.href}
              className="door"
              style={{ "--c": d.color, "--i": i }}
            >
              <span className="doornum">{d.n}</span>
              <h2>{d.label}</h2>
              <p>{d.blurb}</p>
              <span className="doorfoot">
                <span className="doorstat">
                  <Counter value={counts[d.key] ?? null} /> tracked events
                </span>
                <span className="doorarrow" aria-hidden="true">
                  →
                </span>
              </span>
            </Link>
          ))}
        </nav>

        <section className="subscribe" id="subscribe">
          <div className="subcopy">
            <h2>Subscribe for a weekly email digest of state capacity news</h2>
            <p>
              One email, Monday morning. What the states did, what Congress moved, and what the
              agencies put in writing — sorted, not dumped.
            </p>
          </div>

          <div className="subaction">
          <form className="subform" onSubmit={subscribe}>
            <label className="visually-hidden" htmlFor="sub-email">
              Email address
            </label>
            <input
              id="sub-email"
              type="email"
              required
              autoComplete="email"
              placeholder="you@example.gov"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={status.state === "sending"}
            />
            {/* Not visible, not for people. Bots that fill every field get a
                friendly no-op instead of a row. */}
            <input
              className="visually-hidden"
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
              name="company"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
            <button type="submit" disabled={status.state === "sending"}>
              {status.state === "sending" ? "Adding…" : "Subscribe"}
            </button>
          </form>

          <p
            className={`substatus ${status.state}`}
            role="status"
            aria-live="polite"
          >
            {status.message || ""}
          </p>
          </div>
        </section>

        <div className="pair">
          <Link href="/methodology" className="panel">
            <h3>Sources &amp; methodology</h3>
            <p>
              Every feed we read, the rubric each event is scored against, and what the tracker
              deliberately leaves out.
            </p>
            <span className="panelarrow" aria-hidden="true">
              →
            </span>
          </Link>

          <Link href="/make-the-case" className="panel">
            <h3>
              Make the case for state capacity
              <span className="badge">Under construction</span>
            </h3>
            <p>State capacity touches every constituent, through every issue.</p>
            <span className="panelarrow" aria-hidden="true">
              →
            </span>
          </Link>
        </div>

        <footer className="homefoot">
          <p>Recoding America · updated daily, summarised Mondays</p>
          <a href="mailto:atharv@recodingamerica.org?subject=State%20Capacity%20News%20Tracker">
            Contact us with any questions →
          </a>
        </footer>
      </div>
    </main>
  );
}
