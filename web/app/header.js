import Link from "next/link";

/**
 * Site header and tab bar.
 *
 * State Profiles and Governors '26 are deliberately NOT tabs: they are reached
 * from the two buttons at the top of the State Map page, which is their only
 * entry point. Those pages render <Header /> with no `active` — nothing in the
 * bar highlights, which is correct, and they carry their own .pagetitle.
 */
export default function Header({ active }) {
  return (
    <header className="head">
      <h1>State Capacity Tracker</h1>
      <p className="sub">What state governments are actually doing, in Recoding America&apos;s capacities</p>
      <nav className="tabs">
        <Link href="/" className={`tab ${active === "map" ? "on" : ""}`}>
          States
        </Link>
        <Link href="/congress" className={`tab ${active === "congress" ? "on" : ""}`}>
          Congress
        </Link>
        <Link href="/federal" className={`tab ${active === "federal" ? "on" : ""}`}>
          Federal
        </Link>
        <Link href="/methodology" className={`tab ${active === "methodology" ? "on" : ""}`}>
          Sources &amp; methodology
        </Link>
      </nav>
    </header>
  );
}
