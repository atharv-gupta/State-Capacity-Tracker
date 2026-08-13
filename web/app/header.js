import Link from "next/link";

export default function Header({ active }) {
  return (
    <header className="head">
      <h1>State Capacity Tracker</h1>
      <p className="sub">What state governments are actually doing, in Recoding America&apos;s capacities</p>
      <nav className="tabs">
        <Link href="/" className={`tab ${active === "map" ? "on" : ""}`}>
          Map
        </Link>
        <Link href="/states" className={`tab ${active === "states" ? "on" : ""}`}>
          State profiles
        </Link>
        <Link href="/candidates" className={`tab ${active === "candidates" ? "on" : ""}`}>
          Governors &rsquo;26
        </Link>
        <Link href="/congress" className={`tab ${active === "congress" ? "on" : ""}`}>
          Congress
        </Link>
        <Link href="/methodology" className={`tab ${active === "methodology" ? "on" : ""}`}>
          Sources &amp; methodology
        </Link>
      </nav>
    </header>
  );
}
