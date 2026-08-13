import { fetchTable, lines } from "../../lib/airtable";

// Synced from the Congress.gov committee-meeting endpoint by
// congress_api_sync.py. One row per hearing or markup, upserted on
// hearing_key so a reviewer's annotations survive nightly runs.
const TABLE = "Congress Hearings";

export const dynamic = "force-dynamic";

export async function GET() {
  const { records, empty, error, status } = await fetchTable(TABLE);
  if (error) return Response.json({ error }, { status });
  if (empty) return Response.json({ hearings: [] });

  const hearings = records.map((r) => {
    const f = r.fields;
    return {
      id: r.id,
      hearing_key: f.hearing_key || "",
      // Written by the classifier. `title` is Congress.gov's raw agenda text,
      // shown only in the expanded view.
      short_title: f.short_title || f.title || "",
      title: f.title || "",
      agenda_summary: f.agenda_summary || "",
      why_it_matters: f.why_it_matters || "",
      // hearing_date carries the time; date is the YYYY-MM-DD the UI sorts on.
      hearing_date: f.hearing_date || "",
      date: f.date || "",
      committee: f.committee || "",
      chamber: f.chamber || "",
      location: f.location || "",
      witnesses: lines(f.witnesses),
      materials: lines(f.materials_urls),
      bill_refs: f.bill_refs || "",
      meeting_type: f.meeting_type || "",
      hearing_status: f.hearing_status || "",
      competency: f.competency || [],
      relevance: f.relevance || 0,
      topic_tags: f.topic_tags || [],
      review_status: f.review_status || "unreviewed",
      urls: lines(f.source_urls),
    };
  });

  // Ascending: the soonest upcoming hearing is the most useful row.
  hearings.sort((a, b) => (a.date || "").localeCompare(b.date || ""));
  return Response.json({ hearings });
}
