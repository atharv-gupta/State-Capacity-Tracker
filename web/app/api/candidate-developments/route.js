const BASE = process.env.AIRTABLE_BASE_ID;
const TOKEN = process.env.AIRTABLE_TOKEN;
// The clean, deduped layer built weekly by candidates_dedupe.py (one row per
// development, sources merged). The raw per-article table is "Candidate
// Developments"; this tab reads the condensed one.
const TABLE = "Candidate Events";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!BASE || !TOKEN) {
    return Response.json({ error: "Missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID" }, { status: 500 });
  }

  const records = [];
  let offset;
  do {
    const url = new URL(`https://api.airtable.com/v0/${BASE}/${encodeURIComponent(TABLE)}`);
    url.searchParams.set("pageSize", "100");
    if (offset) url.searchParams.set("offset", offset);
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      cache: "no-store",
    });
    if (!res.ok) {
      // Table may not exist until the first pipeline run — treat as empty.
      if (res.status === 404 || res.status === 403) {
        return Response.json({ developments: [] });
      }
      return Response.json({ error: `Airtable ${res.status}` }, { status: 502 });
    }
    const data = await res.json();
    records.push(...data.records);
    offset = data.offset;
  } while (offset);

  const developments = records.map((r) => {
    const f = r.fields;
    return {
      id: r.id,
      candidate: f.candidate || "",
      state: f.state || "",
      date: f.date || "",
      dev_type: f.dev_type || "",
      // Short row title (6-12 words); `headline` is the full sentence shown
      // once expanded. Falls back to the headline for rows written before the
      // field existed — the same shape as the congress route.
      short_title: f.short_title || f.headline || "",
      headline: f.headline || "",
      summary: f.summary || "",
      why_it_matters: f.why_it_matters || "",
      competency: f.competency || [],
      relevance: f.relevance || 0,
      article_count: f.article_count || 1,
      quote: f.quote || "",
      urls: (f.source_urls || "").split("\n").map((s) => s.trim()).filter(Boolean),
      outlets: (f.source_outlets || "").split(",").map((s) => s.trim()).filter(Boolean),
    };
  });

  developments.sort(
    (a, b) => (b.date || "").localeCompare(a.date || "") || b.relevance - a.relevance
  );
  return Response.json({ developments });
}
