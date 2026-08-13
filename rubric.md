# Recoding America State Capacity — Classification Rubric

You classify a single state-government **event** (already deduped and confirmed to be a
real government action). Your job is fit, not provenance. For each event, output:

1. **competencies** — zero or more of `civil-service`, `procedure`, `digital`, `incentives`.
   Most events match none of them — that is expected; return an empty list. Usually an event
   fits exactly one. Assign **two** only when the action is genuinely, substantially about both —
   e.g. legislative **oversight of a failing benefits/IT system** is both `digital` (the system)
   and `incentives` (the oversight). Do not pad the list; a second competency must stand on its own.
2. **relevance** — 1–3, how *central an example* of those competencies this is (see scale); for a
   two-competency event, score the stronger fit. Events that match no competency get no score.
3. **topic_tags** — one or more descriptive tags (independent of competency).

## Principle 1: capacity, not subject matter

These competencies are about **how a state government builds and runs itself** — its own
workforce, its own processes, its own technology, its own learning loops. They are **not**
about the state legislating on a topic in the wider economy or society. A law *about* an
industry, a contract *about* a technology, is usually `none` even when it hits our keywords.
Ask: *is the government changing how it builds and runs itself, or regulating the world
outside it?* Only the former is a competency. Most real government actions are `none` — that
is expected and correct. Never stretch to fit.

## Principle 2: direction doesn't matter — good and bad both count

Relevance measures how central an event is to a competency's **subject**, not whether it's
good or bad for state capacity. An action that *undermines* a competency is still an example
of it, often a strong one. A state **outsourcing its IT** and hollowing out internal capacity
is a textbook `digital` event and scores **3**, even though it cuts directly against the
product-model ideal. Same across the board: a reform that entrenches rigid tenure is a strong
`civil-service` event; a sweeping new compliance regime is a strong `procedure` event;
dismantling a learning loop or punishing reasonable judgment is a strong `incentives` event.
Guardrail: it counts when the event is **primarily about** the competency's machinery — not
when burden or benefit is incidental to a substantive policy (a new pollution rule that
happens to add a form is `none`, not `procedure`).

## Relevance scale (centrality, direction-agnostic)

- **3** — Textbook example of this competency's subject (advancing it *or* undermining it).
- **2** — Clearly an instance, but partial, indirect, or one piece of a larger thing.
- **1** — Loosely related; at the edge of the definition.
- **(empty)** — Fits no competency. Return an empty list; no score.

---

## Civil-service (Workforce)

**Definition.** The foundations of merit-based civil service are sound, but decades of accreted
policy have buried those principles under systems that screen for keywords rather than
competence and make it nearly impossible to reward high performers or remove poor ones. This
spans the full employee lifecycle — hiring, classification, compensation, performance
management, separation — and the gap between what the law already allows and what agencies
actually do. Reform is not rigid tenure vs. pure at-will; it is stripping the system back to
merit principles and shifting the power to evaluate and build teams toward the people
accountable for results.

**Counts when** the action changes how the state hires, classifies, pays, evaluates, promotes,
or separates its own employees, or shifts that authority — **in either direction** (a merit
reform *or* a change that entrenches rigidity).

**Does NOT count** (subject mismatch): private-sector labor law; a budget line that funds
headcount with no change to the workforce *system*.

**Fit:** 3 = a structural change to classification, hiring, or performance/removal (reform or
regression). 1 = a routine personnel action that merely touches the workforce.

---

## Procedure

**Definition.** The layers of process, reporting, documentation, and compliance that accumulate
around every government function until the means crowd out the mission. Each rule makes sense
when added, but the sum is a tyranny of tiny decisions that slows government, drives risk
aversion, and pushes decisions away from the people closest to the work. The test is whether
the harm a procedure guards against is still real, still addressed by the procedure as
practiced, and worth its cost — where not, it should be right-sized or removed.

**Counts when** the action deliberately changes the government's procedural/compliance burden —
**either direction** (a burden-reduction *or* a sweeping new across-the-board mandate regime),
including burden the state imposes on people (permitting, occupational licensing).

**Does NOT count** (subject mismatch): substantive industry or social policy where a reporting
form or process step is incidental, not the point.

**Fit:** 3 = a deliberate change to the procedural apparatus itself. 1 = a minor or incidental
process tweak.

---

## Digital

**Definition.** Digital is not a separate IT function but the infrastructure nearly all modern
government delivery runs on — so getting it right depends on fixing how government funds, staffs,
and oversees technology. It means moving from a project model (software bought once, then left
to rot) to a product model (empowered internal teams continually build, test, and improve the
systems that carry an agency's mission), and rebuilding internal capacity to be a smart buyer
and owner of technology.

**Counts when** the action concerns how the state builds, buys, staffs, uses, or oversees its
**own** technology and data — **in either direction**. This includes laws and policies
governing the **government's own** use and governance of IT, AI, and data: how state agencies
may use AI, how the state handles data, the state's AI-governance framework, IT
reorg/consolidation/outsourcing, product-vs-project moves, and an agency using AI to do its own
work. **Data-privacy and AI-governance laws count whenever they reach the government's own
technology, systems, or data** — e.g. a state AI-governance/transparency act that sets how state
agencies may deploy AI, or a data-privacy law that constrains how the state collects, stores, or
shares the data it holds — **even when the same law also regulates private actors**. If the law
touches the state's own systems or data at all, it counts as `digital`.

**Does NOT count** (subject mismatch): regulation aimed **only** at the **private sector** with no
bearing on the government's own systems — consumer chatbot-disclosure mandates, AI rules for
private healthcare providers, purely company-facing data-privacy laws; data-center
siting/tax/energy/ratepayer policy (economic development & utilities); ed-tech procurement for
schools and universities.

**Test:** does the action govern or affect how *government* builds, buys, uses, or oversees its own
technology and data? → counts. Does it regulate technology **purely** in the private economy,
leaving the state's own systems untouched? → not `digital`.
*Consequence to note:* a data-privacy or AI-governance law that constrains how the **state** handles
its own data or deploys AI is `digital` (even if it also binds private companies); only a purely
consumer/company law with no reach into government systems falls outside `digital`.

**Fit:** 3 = a clear move on the government's own tech operating model (IT reorg, outsourcing,
consolidated service portal, smart-buyer build-out). 1 = tech-adjacent but peripheral.

---

## Incentives (for Outcomes)

**Definition.** Closing the open loop that runs one way from law to policy to implementation,
with little room to learn from what happens and adjust. Funding, oversight, and political reward
today point toward following process and producing new mandates rather than toward whether
programs work — so this means realigning those forces to ask "what are you learning and how will
you adjust." It spans test-and-learn inside agencies, oversight that distinguishes reasonable
judgment from real failure, funding flexible enough to support experimentation, and legislative
habits that reward following up on existing laws as much as passing new ones.

**Counts when** the action changes the learning/feedback loop — **either direction**:
outcome-contingent funding, test-and-learn pilots, accountability/transparency dashboards,
oversight reform, legislative follow-up on existing law — or, negatively, oversight that punishes
reasonable judgment or funding rigid enough to forbid experimentation. (Oversight lives here; it
is not a separate pillar.) **When oversight targets the government's own technology, data, or
benefits systems** — e.g. a committee grilling an agency over a failed IT or benefits platform —
tag **both** `incentives` (the oversight/learning loop) **and** `digital` (the system itself).

**Does NOT count** (subject mismatch): passing a substantive new mandate; a routine compliance
audit that only checks the box.

**Fit:** 3 = an explicit shift in how government learns and adjusts (or a clear step backward).
1 = a faint gesture at accountability.

---

## None

Real government action that isn't about the four internal capacities above: regulating the
private economy or a specific industry; social, criminal-justice, health-delivery, or
environmental policy; economic development; physical infrastructure (incl. data centers as
economic development); classroom ed-tech; elections administration. When torn between a
competency at fit-1 and `none`, prefer `none`.

---

## Topic tags (independent axis — descriptive, multi-select)

Tags are independent of competency; assign any that apply. Many **sector tags** will attach to
`none` events — that's intended, it's how you watch themes (AI, data centers) that aren't
competencies.

**Capacity tags:** `it-modernization`, `ai`, `data-privacy`, `cybersecurity`, `broadband`,
`benefits-systems`, `procurement`, `occupational-licensing`, `permitting`, `housing-land-use`,
`regulatory-reform`, `hiring-recruitment`, `compensation-pensions`, `labor-relations`,
`telework-rto`, `layoffs-rif`, `reorganization`, `transparency`, `study-commission`.

**Sector tags:** `data-center`, `tax-incentives`, `energy-utility`, `health-human-services`,
`higher-ed`, `k12-education`, `child-welfare`.

---

## Output (JSON only, no fences)

```json
{ "competencies": ["digital", "incentives"], "relevance": 3, "topic_tags": ["it-modernization", "transparency"] }
```
For a non-fit: `{ "competencies": [], "relevance": 0, "topic_tags": ["data-center", "tax-incentives"] }`
