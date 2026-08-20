import { fetchTable, lines } from "../../lib/airtable";

// The clean, deduped layer built by federal_dedupe.py — one row per federal
// executive-branch action, with the agency's own release, the Federal Register
// document, the GAO report and every trade-press write-up of it merged into one
// row. The raw per-item table is "Federal Raw"; this tab reads the condensed one.
const TABLE = "Federal Events";

// Registry source names are built for the funnel table, not for a reader:
// "FR agency — MSPB" and "OPM press releases" are the feed, not the publisher.
const OUTLET_LABELS = {
  "OPM press releases": "OPM",
  "OMB memoranda": "OMB",
  "OMB news": "OMB",
  "GSA news releases": "GSA",
  "GAO reports": "GAO",
};

function outletLabel(name) {
  if (OUTLET_LABELS[name]) return OUTLET_LABELS[name];
  // Every Federal Register query is named "FR agency — X" / "FR term — X".
  if (name.startsWith("FR ")) return "Federal Register";
  return name;
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

// Publisher names keyed by host. Labelling from the URL rather than from the
// parallel `source_outlets` list is the robust choice: when one cluster holds
// two articles from the same outlet, the outlets list dedupes and the two lists
// stop lining up, which was mislabelling rows. An unmapped host falls back to
// the bare hostname, which reads acceptably on its own.
const HOST_LABELS = {
  "federalregister.gov": "Federal Register",
  "whitehouse.gov": "White House / OMB",
  "opm.gov": "OPM",
  "gsa.gov": "GSA",
  "gao.gov": "GAO",
  "congress.gov": "Congress.gov",
  "fedscoop.com": "FedScoop",
  "nextgov.com": "Nextgov/FCW",
  "govexec.com": "Government Executive",
  "federalnewsnetwork.com": "Federal News Network",
  "meritalk.com": "MeriTalk",
  "thehill.com": "The Hill",
  "route-fifty.com": "Route Fifty",
  "washingtontechnology.com": "Washington Technology",
};

/**
 * Label each source URL and mark whether it is a government primary source or
 * press coverage.
 *
 * A clustered event routinely holds both — the Federal Register rule AND the
 * Federal News Network story about it, the GAO report AND the FedScoop
 * write-up — and the reader wants one of each, not whichever happened to sort
 * first. The .gov test is what separates them; it covers federalregister.gov,
 * whitehouse.gov, opm.gov, gsa.gov and gao.gov with no host list to maintain.
 */
function buildSources(urls) {
  return urls.map((url) => {
    const host = hostOf(url);
    return {
      url,
      outlet: HOST_LABELS[host] || host,
      kind: host.endsWith(".gov") ? "primary" : "press",
    };
  });
}

export const dynamic = "force-dynamic";

export async function GET() {
  const { records, empty, error, status } = await fetchTable(TABLE);
  if (error) return Response.json({ error }, { status });
  if (empty) return Response.json({ events: [] });

  const events = records.map((r) => {
    const f = r.fields;
    return {
      id: r.id,
      event_id: f.event_id || "",
      short_title: f.short_title || f.headline || "",
      headline: f.headline || "",
      summary: f.summary || "",
      why_it_matters: f.why_it_matters || "",
      date: f.date || "",
      // Which of the three sections the row belongs in. Set by the source and
      // resolved to the highest-provenance member of the cluster, so an OMB
      // memo covered by five outlets files as an executive action, not as news.
      lane: f.lane || "news",
      branch: f.branch || "executive",
      agency: f.agency || [],
      instrument_type: f.instrument_type || "",
      instrument_id: f.instrument_id || "",
      // official / reported / draft-leaked — trade-press reporting on a draft
      // memo is kept and labelled rather than dropped.
      verification: f.verification || "",
      competency: f.competency || [],
      relevance: f.relevance || 0,
      topic_tags: f.topic_tags || [],
      actor: f.actor || "",
      status: f.status || "",
      document_url: f.document_url || "",
      article_count: f.article_count || 1,
      review_status: f.review_status || "unreviewed",
      urls: lines(f.source_urls),
      outlets: lines(f.source_outlets).map(outletLabel),
      // One entry per source, labelled and split into primary vs press so the
      // UI can offer a link to one of each instead of just the first URL.
      sources: buildSources(lines(f.source_urls)),
    };
  });

  events.sort(
    (a, b) => (b.date || "").localeCompare(a.date || "") || b.relevance - a.relevance
  );
  return Response.json({ events });
}
