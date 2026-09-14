import Link from "next/link";

/**
 * Site header and tab bar, on every page except the landing page — that one
 * carries its own hero and needs no second copy of the title.
 *
 * State Profiles and Governors '26 are deliberately NOT tabs: they are reached
 * from the two buttons at the top of the State Map page, which is their only
 * entry point. Those pages render <Header /> with no `active` — nothing in the
 * bar highlights, which is correct, and they carry their own .pagetitle.
 *
 * "Make the case" IS a tab while it is still a stub, because a section nobody
 * can find is a section nobody will write. The `soon` flag marks it as unbuilt
 * in the one place a reader would otherwise click it expecting a page.
 */
const TABS = [
  { href: "/states", key: "states", label: "States" },
  { href: "/congress", key: "congress", label: "Congress" },
  { href: "/federal", key: "federal", label: "Federal" },
  { href: "/make-the-case", key: "case", label: "Make the case", soon: true },
  { href: "/methodology", key: "methodology", label: "Sources & methodology" },
];

export default function Header({ active }) {
  return (
    <header className="head">
      <h1>
        <Link href="/" className="homelink">
          State Capacity News Tracker
        </Link>
      </h1>
      <p className="sub">
        Follow along with what governments are doing in the world of state capacity
      </p>
      <nav className="tabs">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.href}
            className={`tab ${active === t.key ? "on" : ""}`}
          >
            {t.label}
            {t.soon ? <span className="tabsoon">soon</span> : null}
          </Link>
        ))}
      </nav>
    </header>
  );
}
