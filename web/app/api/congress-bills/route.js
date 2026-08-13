import { fetchTable, lines } from "../../lib/airtable";

// Synced from the Congress.gov committee-bills endpoint by
// congress_api_sync.py — bills referred to or reported by the seven tracked
// committees, upserted on bill_id so status changes update in place.
const TABLE = "Congress Bills";

export const dynamic = "force-dynamic";

export async function GET() {
  const { records, empty, error, status } = await fetchTable(TABLE);
  if (error) return Response.json({ error }, { status });
  if (empty) return Response.json({ bills: [] });

  const bills = records.map((r) => {
    const f = r.fields;
    return {
      id: r.id,
      bill_id: f.bill_id || "",
      bill_number: f.bill_number || "",
      congress: f.congress || 0,
      title: f.title || "",
      summary: f.summary || "",
      why_it_matters: f.why_it_matters || "",
      date: f.date || "",
      introduced_date: f.introduced_date || "",
      committee: f.committee || "",
      chamber: f.chamber || "",
      sponsor: f.sponsor || "",
      sponsor_party: f.sponsor_party || "",
      cosponsor_count: f.cosponsor_count || 0,
      latest_action: f.latest_action || "",
      latest_action_date: f.latest_action_date || "",
      bill_status: f.bill_status || "",
      policy_area: f.policy_area || "",
      competency: f.competency || [],
      relevance: f.relevance || 0,
      topic_tags: f.topic_tags || [],
      review_status: f.review_status || "unreviewed",
      urls: lines(f.source_urls),
    };
  });

  // Relevance first, unlike events. Bills are a standing list rather than a
  // news feed — a committee's most capacity-relevant bill should lead even if
  // a post-office naming saw action more recently.
  bills.sort(
    (a, b) => b.relevance - a.relevance || (b.date || "").localeCompare(a.date || "")
  );
  return Response.json({ bills });
}
