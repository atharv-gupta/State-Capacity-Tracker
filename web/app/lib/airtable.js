const BASE = process.env.AIRTABLE_BASE_ID;
const TOKEN = process.env.AIRTABLE_TOKEN;

/**
 * Read every record from an Airtable table, following the offset cursor.
 *
 * The four original /api routes each inline this loop; this is the shared
 * version the congress routes use instead of adding three more copies.
 *
 * Returns { records } on success, { empty: true } when the table doesn't
 * exist yet (so a tab renders before the first pipeline run has created it),
 * or { error, status } otherwise.
 */
export async function fetchTable(table) {
  if (!BASE || !TOKEN) {
    return { error: "Missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID", status: 500 };
  }

  const records = [];
  let offset;
  do {
    const url = new URL(`https://api.airtable.com/v0/${BASE}/${encodeURIComponent(table)}`);
    url.searchParams.set("pageSize", "100");
    if (offset) url.searchParams.set("offset", offset);

    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      cache: "no-store",
    });
    if (!res.ok) {
      if (res.status === 404 || res.status === 403) return { empty: true };
      return { error: `Airtable ${res.status}`, status: 502 };
    }
    const data = await res.json();
    records.push(...data.records);
    offset = data.offset;
  } while (offset);

  return { records };
}

/** Newline-delimited multiline text -> array of trimmed non-empty lines. */
export function lines(value) {
  return (value || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}
