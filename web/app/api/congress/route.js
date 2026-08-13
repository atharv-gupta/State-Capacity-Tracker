import { fetchTable, lines } from "../../lib/airtable";

// The clean, deduped layer built by congress_dedupe.py — one row per event,
// majority/minority write-ups of the same action merged. The raw per-item
// table is "Congress Raw"; this tab reads the condensed one.
const TABLE = "Congress Events";

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
      headline: f.headline || "",
      summary: f.summary || "",
      why_it_matters: f.why_it_matters || "",
      date: f.date || "",
      committee: f.committee || "",
      chamber: f.chamber || "",
      party_source: f.party_source || "",
      activity_type: f.activity_type || "",
      competency: f.competency || [],
      relevance: f.relevance || 0,
      topic_tags: f.topic_tags || [],
      actor: f.actor || "",
      bill_refs: f.bill_refs || "",
      status: f.status || "",
      article_count: f.article_count || 1,
      review_status: f.review_status || "unreviewed",
      urls: lines(f.source_urls),
      outlets: lines(f.source_outlets),
    };
  });

  events.sort(
    (a, b) => (b.date || "").localeCompare(a.date || "") || b.relevance - a.relevance
  );
  return Response.json({ events });
}
