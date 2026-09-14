import Header from "../header";

export const metadata = {
  title: "Make the case — State Capacity News Tracker",
  description:
    "The arguments, the evidence, and the language for making the case for state capacity.",
};

/**
 * A stub with a tab, on purpose.
 *
 * The section is in the nav before it is written because the nav is where it
 * will be looked for, and a tab that says "not yet" costs a reader less than a
 * tab that appears one day with no warning. The "soon" flag in header.js and
 * the notice here are the two places that have to agree; when the real page
 * lands, both come out.
 */
export default function MakeTheCase() {
  return (
    <main className="wrap">
      <Header active="case" />

      <div className="pagelead">
        <h2 className="pagetitle">Make the case for state capacity</h2>
      </div>

      <section className="stub">
        <h3>Under construction</h3>
      </section>
    </main>
  );
}
