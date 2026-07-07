const BASE = process.env.AIRTABLE_BASE_ID;
const TOKEN = process.env.AIRTABLE_TOKEN;
const TABLE = "Gov Candidates";

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
      return Response.json({ error: `Airtable ${res.status}` }, { status: 502 });
    }
    const data = await res.json();
    records.push(...data.records);
    offset = data.offset;
  } while (offset);

  const candidates = records.map((r) => {
    const f = r.fields;
    return {
      id: r.id,
      name: f.candidate || "",
      state: f.state || "",
      party: f.party || "",
      status: f.status || "",
      role: f.current_role || "",
      race_type: f.race_type || "",
      race_rating: f.race_rating || "",
      primary_date: f.primary_date || "",
      primary_held: !!f.primary_held,
      website: f.website || "",
      platform_summary: f.platform_summary || "",
      competency_signals: f.competency_signals || [],
      platform_sources: (f.platform_sources || "").split("\n").map((s) => s.trim()).filter(Boolean),
      platform_asof: f.platform_asof || "",
      notes: f.notes || "",
    };
  });

  candidates.sort(
    (a, b) => a.state.localeCompare(b.state) || a.name.localeCompare(b.name)
  );
  return Response.json({ candidates });
}
