> **Superseded as of 2026-08-31 — kept as the original handoff spec, not as current
> behaviour.** Phase 1 is done. `updates.recodingamerica.org` is verified, the digest
> sends from `digest@updates.recodingamerica.org`, and recipients come from the
> `Digest Recipients` Airtable table rather than a hard-coded list. Each recipient now
> receives their own message with their own unsubscribe link — see the "Weekly email
> digest" section of the README. The §0 constraints below (send only from
> `onboarding@resend.dev`, only to the account address) no longer apply.

# Feature brief: weekly email digest (`digest.py`)

A handoff spec for Claude Code. Build a new script that runs **right after `dedupe.py`** each week and emails a digest of the most notable state-capacity events. **Phase 1 (now): send to one hard-coded recipient — `atharv@recodingamerica.fund` — via Resend's pre-verification sender.** Designed so the recipient source can later become a signup table, and the sending domain can flip to the real Recoding America domain, without touching the selection/formatting logic.

---

## 0. READ THIS FIRST — the pre-DNS sending constraint

The Resend account has **not yet verified a domain** (DNS access is pending). Until it does, Resend enforces a hard rule:

- Mail can only be sent **from** `onboarding@resend.dev`.
- Mail can only be delivered **to the email address the Resend account was created with** — which is **`atharv@recodingamerica.fund`**. Any other recipient returns a `403` / validation error from the Resend API.

**Implications for this build:**
- `RECIPIENTS` must be exactly `["atharv@recodingamerica.fund"]`. Do not add other addresses yet — they will fail, not just degrade.
- `DIGEST_FROM` is `onboarding@resend.dev` for now (read from env; already set as a secret).
- The send function **must surface Resend's full error response** (status + body) on failure, so a misconfiguration is obvious rather than silent. The most likely error during testing is the "you can only send to your own address" 403 — if it appears, the recipient or the account email is the problem, not the code.

When DNS is later verified, the only changes are: flip `DIGEST_FROM` to a real address (e.g. `digest@updates.recodingamerica.fund`) and expand `RECIPIENTS` / swap in a subscriber source. Nothing else in this spec changes.

---

## 1. Where it fits

- `pipeline.py` runs daily (ingest → `Raw Events`).
- `dedupe.py` runs weekly on Mondays (cluster + classify → `Events`).
- **New:** `digest.py` runs immediately after the weekly dedupe, reads the `Events` table for the week just built, composes one email, and sends it.

Add it as a sibling of `pipeline.py` / `dedupe.py`, reusing the same Airtable client and `.env` plumbing. It must run unattended in GitHub Actions (so no interactive auth, no reliance on any Claude.ai connector — the runner only has repo secrets).

---

## 2. Data source & window

- Read from the **`Events`** table (not `Raw Events`, not `old_Events`).
- Filter to events whose **`date`** falls in the last **N days**, default **7**, via a `--days` flag — so the digest window matches the dedupe window that just ran. The workflow passes the same value to both (`dedupe.py --days 7` then `digest.py --days 7`).
- **Field-name caveat — read carefully:** the original prompt called this a "significance score," but the live `Events` model uses **`relevance` (integer 1–3)**. `significance` only exists on the legacy `old_Events` table. All selection logic below keys off **`relevance`**. Do not read `significance`.

---

## 3. Selection logic (the core of the feature)

Four categories, matching the `competency` field values exactly:
`civil-service`, `procedure`, `digital`, `incentives`.

For **each** category independently:

1. Take **every** event whose `competency` includes that category **and** `relevance == 3`. Always all of them, however many.
2. If that gives **4 or fewer** events, top up with `relevance == 2` events (same category) **until the running total exceeds 4** (i.e. reaches 5) **or** the 2's are exhausted.
3. If `relevance == 3` already gives 5+ events, include **no** 2's.

Pseudocode:

```python
COMPETENCIES = ["civil-service", "procedure", "digital", "incentives"]

def select(events, comp):
    in_comp = [e for e in events if comp in e["competency"]]
    threes  = [e for e in in_comp if e["relevance"] == 3]
    twos    = sorted(
        (e for e in in_comp if e["relevance"] == 2),
        key=rank,                       # see decision below
    )
    selected = list(threes)             # all 3's, unconditionally
    i = 0
    while len(selected) <= 4 and i < len(twos):
        selected.append(twos[i]); i += 1
    return selected
```

Worked examples to assert against: 6 threes → 6; 4 threes → 4 + 1 two = 5; 2 threes + 1 two → 3; 0 threes + 10 twos → 5; 0 threes + 3 twos → 3.

---

## 4. Decisions (previously open — now settled, build to these)

- **Ordering of 2's (`rank`)** — most-covered then most-recent: `key=lambda e: (-e["article_count"], -e["date_epoch"])`. (Matters because 2's get truncated.)
- **Events spanning two competencies** — let them appear in **each** relevant section (full context per category). Implement behind a top-of-file flag `DEDUPE_ACROSS_SECTIONS = False` so it can be flipped later.
- **Empty category** — render the section header with a one-line `Nothing notable this week.`
- **Summary source** — use **`why_it_matters`** if present; else the first 1–2 sentences of `Notes`. Never dump the full `Notes`.
- **Email provider** — **Resend** (decided; see §6). Keep it isolated in one function so it's swappable, but Resend is the only implementation needed now.

---

## 5. Email content & format

One email, four sections in the fixed order above. Send **both** an HTML body and a plaintext fallback (multipart/alternative — Resend accepts `html` and `text` fields).

- **Subject:** `State Capacity Digest — week of {Monday date}: {total} events`
- **Per section:** category name as a header, then the selected events.
- **Per event:**
  - **Title** — the `Name` field (bold; in HTML, link it to the first source URL).
  - **Summary** — one short paragraph (`why_it_matters`, with the `Notes` fallback above).
  - **Meta line** — `{state} · {activity_type} · {gov_actor}` and a relevance marker (e.g. `●●●` / `●●`).
  - **Links** — render each `source_outlets[i]` as a link to `source_urls[i]`. If the arrays differ in length, fall back to listing the raw URLs.
- Keep the HTML simple and email-client-safe (inline styles, single simple table or none, no external CSS/JS). Readable and text-forward, not a designed newsletter.

---

## 6. Sending (Resend)

All provider-specific code lives in one function:

```python
def send_email(subject: str, html: str, text: str, recipients: list[str]) -> None:
    ...
```

Implementation: POST to the Resend API (`https://api.resend.com/emails`) with `Authorization: Bearer {RESEND_API_KEY}`, body `{from, to, subject, html, text}`. Use the `resend` Python SDK or plain `requests` — either is fine; if adding a dependency, pin it in `requirements.txt`.

- `from` = env `DIGEST_FROM` (currently `onboarding@resend.dev`).
- `to` = `recipients` (currently the single self-address — see §0).
- On non-2xx, raise with the status code **and response body** included in the message.
- Recipients come from a `get_recipients()` function that today returns the `RECIPIENTS` constant. This is the only thing that changes when a subscriber model arrives later — do not thread the list through the rest of the code.
- When the list eventually grows, send as BCC (or individual sends) so addresses aren't exposed. For the single-recipient phase this is moot.

**Secrets — already configured** (local `.env` + GitHub Actions secrets):
`ANTHROPIC_API_KEY`, `AIRTABLE_TOKEN`, `AIRTABLE_BASE_ID` (pre-existing), `RESEND_API_KEY`, `DIGEST_FROM`.

---

## 7. CLI / running

```bash
.venv/bin/python digest.py --days 7              # compose + send to RECIPIENTS
.venv/bin/python digest.py --days 7 --dry-run    # render HTML+text + per-category counts to stdout; send nothing
.venv/bin/python digest.py --days 7 --to me@x.com  # override recipient (only works post-DNS; pre-DNS must be the account address)
```

`--dry-run` must print, per category, the selected events and a count, so the §3 rule is eyeballable without sending.

---

## 8. The Monday self-test (this is the immediate goal)

Two ways to verify, in increasing realism:

1. **Local dry run, any time before Monday** — `digest.py --days 7 --dry-run` against the existing `Events` data. Confirms selection + formatting with zero send. Do this first.
2. **Local real send to self, any time** — `digest.py --days 7` with `RECIPIENTS = ["atharv@recodingamerica.fund"]`. Confirms the Resend path end-to-end. The email should arrive from `onboarding@resend.dev`; check spam/Promotions the first time and mark it safe.
3. **The actual Monday automated test** — the workflow runs `dedupe.py` then `digest.py` on Monday; the digest lands in Atharv's inbox automatically. The manual `workflow_dispatch` trigger (below) lets this be rehearsed before Monday too.

A successful test = the email arrives, the four sections render, the §3 counts look right, and links work. A `403` about sending to your own address means the recipient ≠ the Resend account address (see §0).

---

## 9. Workflow integration

In `.github/workflows/weekly.yml`, the Monday dedupe step is followed by a digest step (same window, same Monday condition):

```yaml
- name: Dedupe (Mondays)
  if: <existing Monday condition>
  run: .venv/bin/python dedupe.py --days 7

- name: Send weekly digest (Mondays)
  if: <same Monday condition>
  run: .venv/bin/python digest.py --days 7
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    AIRTABLE_TOKEN:     ${{ secrets.AIRTABLE_TOKEN }}
    AIRTABLE_BASE_ID:   ${{ secrets.AIRTABLE_BASE_ID }}
    RESEND_API_KEY:     ${{ secrets.RESEND_API_KEY }}
    DIGEST_FROM:        ${{ secrets.DIGEST_FROM }}
```

- Ensure the existing manual `workflow_dispatch` can also reach the digest step (an opt-in input, mirroring the existing dedupe checkbox), so the Monday run can be rehearsed on demand.
- A failed send should surface as a failed step but must not roll back the dedupe. `digest.py` is read-only against Airtable, so this is naturally safe.

---

## 10. Acceptance criteria

- [ ] `digest.py --days 7 --dry-run` prints, per category, the selected events and a count, obeying the §3 rule on real data.
- [ ] All `relevance == 3` events in-window appear; 2's appear only when a category has ≤4 threes, capped at first-crossing-5; 2's ordered by §4 rank.
- [ ] Reads `relevance` from `Events` (never `significance` / `old_Events`).
- [ ] Each event renders title, summary (`why_it_matters` → `Notes` fallback), meta line, and working source links.
- [ ] HTML + plaintext; renders cleanly in Gmail.
- [ ] `RECIPIENTS == ["atharv@recodingamerica.fund"]`; recipients sourced via `get_recipients()`.
- [ ] `from` = `DIGEST_FROM`; provider code confined to `send_email()`.
- [ ] Failed sends raise with Resend's status + body.
- [ ] A real run delivers the digest to `atharv@recodingamerica.fund` end-to-end (the Monday test).
