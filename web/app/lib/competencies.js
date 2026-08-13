/**
 * The four Recoding America competencies and their colors.
 *
 * These were duplicated across page.js, states/specs-meta.js and
 * methodology/page.js. New code imports from here; the congress tab is the
 * first consumer.
 */
export const COMPETENCIES = [
  { key: "civil-service", label: "Civil service", color: "#059669" },
  { key: "procedure", label: "Procedure", color: "#d97706" },
  { key: "digital", label: "Digital", color: "#2563eb" },
  { key: "incentives", label: "Incentives", color: "#7c3aed" },
];

export const COMPETENCY_COLOR = Object.fromEntries(
  COMPETENCIES.map((c) => [c.key, c.color])
);

export const DEFAULT_COMPETENCIES = COMPETENCIES.map((c) => c.key);

/**
 * Cutoff date for a rolling window, as YYYY-MM-DD.
 *
 * Airtable dates are ISO strings, so callers compare lexically
 * (`row.date >= cutoff`). `null` days means "all time" and returns null.
 *
 * page.js and candidates/page.js each define their own copy of this with
 * different window vocabularies; this is the shared one.
 */
export function cutoffFor(days) {
  if (days == null) return null;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Today as YYYY-MM-DD, for splitting upcoming vs. past. */
export function today() {
  return new Date().toISOString().slice(0, 10);
}
