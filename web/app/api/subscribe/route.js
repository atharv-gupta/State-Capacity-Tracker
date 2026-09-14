/**
 * Sign-up endpoint for the weekly digest. Writes to the same
 * `Digest Recipients` table that tracker/digest.py reads at send time, so a
 * row created here is picked up by the next Monday send with no other step.
 *
 * This is the only route on the site that WRITES to Airtable, and the only one
 * reachable by an anonymous stranger, so it is deliberately narrow:
 *
 *   * exactly two fields are accepted from the body, and `name` is optional
 *   * the email is validated before it is ever interpolated into a formula
 *   * a resubscribe reactivates the existing row rather than adding a second
 *     one — the digest de-duplicates by address anyway, but a table with two
 *     rows for one person is a table nobody trusts
 *   * an unsubscribed row is only ever revived by an explicit post from that
 *     address, which is what this is
 *   * Airtable's own error text is logged, never returned: it names the base
 *     and the table, and this response is public
 */

const BASE = process.env.AIRTABLE_BASE_ID;
const TOKEN = process.env.AIRTABLE_TOKEN;
const TABLE = "Digest Recipients";

export const dynamic = "force-dynamic";

// Same shape tracker/digest.py accepts (EMAIL_RE), plus a length ceiling.
// Deliberately loose about what an address may contain and strict about the
// characters that would matter downstream: no quotes, no backslashes and no
// whitespace can survive this, which is what makes the filterByFormula below
// safe to build by concatenation.
const EMAIL_RE = /^[^@\s"'\\]+@[^@\s"'\\]+\.[^@\s"'\\]+$/;

// One instance, one map. This does not survive a redeploy or span serverless
// instances, so it is a speed bump for a crude script rather than real rate
// limiting — enough to stop a loop from filling the table, not enough to call
// this endpoint protected. A real limit needs shared state.
const WINDOW_MS = 60 * 1000;
const MAX_PER_WINDOW = 5;
const hits = new Map();

function rateLimited(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 500) {
    for (const [k, v] of hits) if (!v.some((t) => now - t < WINDOW_MS)) hits.delete(k);
  }
  return recent.length > MAX_PER_WINDOW;
}

const api = (path, init) =>
  fetch(`https://api.airtable.com/v0/${BASE}/${encodeURIComponent(TABLE)}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });

export async function POST(request) {
  if (!BASE || !TOKEN) {
    console.error("subscribe: missing AIRTABLE_TOKEN / AIRTABLE_BASE_ID");
    return Response.json({ error: "Sign-up is not configured yet." }, { status: 500 });
  }

  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0].trim() ||
    request.headers.get("x-real-ip") ||
    "unknown";
  if (rateLimited(ip)) {
    return Response.json({ error: "Too many attempts. Try again in a minute." }, { status: 429 });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Bad request." }, { status: 400 });
  }

  // Honeypot: a field no human sees and no human fills. Bots that post every
  // input they find get a cheerful 200 and no row.
  if (body?.company) return Response.json({ ok: true, already: true });

  const email = String(body?.email || "").trim();
  const name = String(body?.name || "").trim().slice(0, 100);

  if (email.length > 254 || !EMAIL_RE.test(email)) {
    return Response.json({ error: "That doesn't look like an email address." }, { status: 400 });
  }

  try {
    // Existing row? Airtable has no case-insensitive unique index, so ask for
    // one by lowercased address.
    const lookup = await api(
      `?pageSize=1&filterByFormula=${encodeURIComponent(
        `LOWER({email})="${email.toLowerCase()}"`
      )}`
    );
    if (!lookup.ok) throw new Error(`lookup ${lookup.status}: ${await lookup.text()}`);
    const existing = (await lookup.json()).records?.[0];

    if (existing) {
      if ((existing.fields.status || "").toLowerCase() === "active") {
        return Response.json({ ok: true, already: true });
      }
      const patch = await api("", {
        method: "PATCH",
        body: JSON.stringify({
          records: [
            {
              id: existing.id,
              fields: { status: "active", unsubscribed_at: null },
            },
          ],
        }),
      });
      if (!patch.ok) throw new Error(`patch ${patch.status}: ${await patch.text()}`);
      return Response.json({ ok: true, resubscribed: true });
    }

    const create = await api("", {
      method: "POST",
      body: JSON.stringify({
        records: [
          {
            fields: {
              email,
              ...(name ? { name } : {}),
              status: "active",
              source: "self-signup",
              added_at: new Date().toISOString().slice(0, 10),
            },
          },
        ],
      }),
    });
    if (!create.ok) throw new Error(`create ${create.status}: ${await create.text()}`);

    return Response.json({ ok: true });
  } catch (e) {
    console.error("subscribe:", e);
    return Response.json({ error: "Couldn't save that just now. Try again shortly." }, { status: 502 });
  }
}
