// Shared metadata for the State Specs views (landing map/table + profile cards).
// Mirrors the schema in docs/specs/static-state-specs.md §2. Keep field keys in sync with
// the Airtable field names and /api/state-specs.

// The four buckets, each with its provenance pair (source URL + as-of date) and
// the metrics that render as label -> chip. `notes` are free-text fields shown
// as prose under the chips.
export const GROUPS = [
  {
    key: "basic",
    title: "Basic",
    color: "#0f172a",
    source: "basic_source",
    asof: "basic_asof",
    fields: [
      { key: "partisan_lean", label: "Partisan lean" },
      { key: "trifecta", label: "Trifecta" },
      { key: "governor_name", label: "Governor", plain: true },
      { key: "governor_party", label: "Party" },
      { key: "gov_term_limit", label: "Term limit" },
      { key: "gov_terms_remaining", label: "Eligibility" },
      { key: "gov_next_election", label: "Next election", plain: true },
    ],
    notes: [{ key: "partisan_lean_basis", label: "Lean basis" }],
  },
  {
    key: "civil",
    title: "Civil service",
    color: "#059669",
    source: "civilservice_source",
    asof: "civilservice_asof",
    fields: [
      { key: "collective_bargaining", label: "Collective bargaining" },
      { key: "hr_authority_model", label: "HR authority" },
      { key: "merit_protection", label: "Merit protection" },
    ],
    notes: [
      { key: "cb_note", label: "Bargaining carve-outs" },
      { key: "napa_note", label: "NAPA notes" },
    ],
  },
  {
    key: "digital",
    title: "Digital",
    color: "#2563eb",
    source: "digital_source",
    asof: "digital_asof",
    fields: [
      { key: "ai_leadership", label: "AI leadership" },
      { key: "digital_service_team", label: "Digital service team" },
    ],
    notes: [],
  },
  {
    key: "procedure",
    title: "Procedure (APA)",
    color: "#d97706",
    source: "procedure_source",
    asof: "procedure_asof",
    fields: [
      { key: "rulemaking_form", label: "Rulemaking form" },
      { key: "executive_review", label: "Executive review" },
      { key: "executive_review_who", label: "Reviewed by", plain: true },
      { key: "legislative_review", label: "Legislative review" },
      { key: "independent_agency_review", label: "Independent-agency review" },
      { key: "impact_analysis", label: "Impact analysis" },
      { key: "periodic_review", label: "Periodic review" },
    ],
    notes: [],
  },
];

// Exact-match colors for enum chips. Anything not listed renders neutral slate.
export const CHIP_COLORS = {
  // partisan_lean + trifecta
  Red: "#dc2626", Republican: "#dc2626",
  Blue: "#2563eb", Democratic: "#2563eb",
  Purple: "#7c3aed", Divided: "#7c3aed",
  // governor_party
  R: "#dc2626", D: "#2563eb", Independent: "#6b7280",
  // collective_bargaining
  "Duty to bargain": "#059669",
  "Permits voluntary": "#d97706",
  "Prohibits / no provision": "#dc2626",
  // generic yes/no
  Yes: "#059669", No: "#94a3b8", Disbanded: "#dc2626",
  // ai_leadership
  "Named CAIO/AI lead": "#059669",
  "AI leadership office": "#2563eb",
  "Council/task force only": "#d97706",
  "None formal": "#94a3b8",
};

export function chipColor(v) {
  return CHIP_COLORS[v] || "#64748b";
}

// Map-coloring lenses on the landing page.
export const LENSES = [
  {
    key: "trifecta",
    label: "Trifecta",
    colors: { Republican: "#dc2626", Democratic: "#2563eb", Divided: "#a78bfa" },
    legend: [
      ["Republican", "#dc2626"],
      ["Democratic", "#2563eb"],
      ["Divided", "#a78bfa"],
    ],
  },
  {
    key: "partisan_lean",
    label: "Partisan lean",
    colors: { Red: "#dc2626", Purple: "#a78bfa", Blue: "#2563eb" },
    legend: [
      ["Red", "#dc2626"],
      ["Purple", "#a78bfa"],
      ["Blue", "#2563eb"],
    ],
  },
];

// The compare table shows one bucket of columns at a time, chosen by the buttons
// at the top. `State` is always prepended. `filter: true` => per-column dropdown;
// filters persist across buckets so cross-bucket queries still work.
export const TABLE_BUCKETS = [
  {
    key: "basic",
    label: "Basic",
    cols: [
      { key: "partisan_lean", label: "Lean", filter: true },
      { key: "trifecta", label: "Trifecta", filter: true },
      { key: "governor_name", label: "Governor", plain: true },
      { key: "governor_party", label: "Party", filter: true },
      { key: "gov_term_limit", label: "Term limit", filter: true },
      { key: "gov_terms_remaining", label: "Eligibility", filter: true },
      { key: "gov_next_election", label: "Next elec.", plain: true, filter: true },
    ],
  },
  {
    key: "civil",
    label: "Civil service",
    cols: [
      { key: "collective_bargaining", label: "Collective bargaining", filter: true },
      { key: "hr_authority_model", label: "HR model", filter: true },
      { key: "merit_protection", label: "Merit protection", filter: true },
    ],
  },
  {
    key: "digital",
    label: "Digital",
    cols: [
      { key: "ai_leadership", label: "AI leadership", filter: true },
      { key: "digital_service_team", label: "Digital service team", filter: true },
    ],
  },
  {
    key: "procedure",
    label: "APA",
    cols: [
      { key: "rulemaking_form", label: "Rulemaking", filter: true },
      { key: "executive_review", label: "Exec. review", filter: true },
      { key: "legislative_review", label: "Leg. review", filter: true },
      { key: "independent_agency_review", label: "Indep. agency", filter: true },
      { key: "impact_analysis", label: "Impact analysis", filter: true },
      { key: "periodic_review", label: "Periodic rev.", filter: true },
    ],
  },
];

export const STATE_COL = { key: "postal", label: "State", filter: false };

// flat lookup colKey -> label, across every bucket (for active-filter chips)
export const COL_LABELS = Object.fromEntries(
  TABLE_BUCKETS.flatMap((b) => b.cols.map((c) => [c.key, c.label]))
);
