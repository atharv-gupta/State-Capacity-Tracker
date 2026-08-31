"""The spec for the one-line `why_it_matters` that appears under an event on the
tracker and in the weekly digest.

This used to be a single phrase inside each JSON contract — "one line for a
Recoding America reader" — repeated in four files. That vacuum is what produced
the house style everyone disliked: the model had nothing to go on but the
rubric's own vocabulary, so 11% of lines contained "capacity" and 5%
"machinery", and most restated the competency the reader could already see on
the chip.

These rules were derived from a blind A/B against 60 real events, marked by the
team, then a second round on the 20 hardest. In the second round the general
rules won 9 of 10 on rows that had previously drawn complaints. Two blocks,
because candidates need the opposite of what enacted actions need — see
CANDIDATE_RULES.

If you change these, re-run the comparison rather than editing on instinct; the
workbooks in review/ are the fixture.
"""

# Shared by every tracker. The tail ban is first because it was by far the most
# common complaint: the model kept writing a good concrete line, an em dash, and
# then a speculative clause the reviewer struck every time.
_COMMON = """
STOP AT WHAT IS KNOWN. Write the concrete observation and then stop. Do not append a
clause speculating about what happens next. Never write "— whether X will Y is the open
question", "the real test is whether", "remains to be seen", "will determine if",
"depends on how", or "watch whether". If your sentence contains an em dash followed by
"whether", delete from the em dash onward and check whether the line is finished. It
usually is, and it is usually better.

Do not infer intent. You do not know what an actor is thinking, gambling on, or hoping
for. Say what they did and what it does: "Peters is pushing for public pressure to
convert IG findings into binding action", never "Peters is betting that...".

Do not guess at impact nobody has observed yet. If the outcome depends on
implementation no one has seen, say what changed, not what might result.

GROUNDING IS ABSOLUTE. Every fact must come from the material you are given. No figures,
headcounts, dollar amounts, durations, rankings, or "X other states also..." comparisons
from your own knowledge, however confident you are. If a number is not in the material
in front of you, it does not go in. An unverifiable statistic on a public tracker is a
worse failure than a plain sentence.

REGISTER IS FLAT. Report; do not characterise. Avoid "rare", "chronic", "striking",
"a bad sign", "quietly", "remarkable", "textbook". Prefer "noteworthy" to "rare",
"a chokepoint" to "the chronic chokepoint". Never use "capacity", "capacities",
"machinery", "underscores", "highlights", "signals", or "speaks to".

LENGTH: at most 30 words, one sentence. Most good lines are 20-25. Do not open with
"This", "The move", or "The measure". Every item gets a line — never return empty.

BEFORE YOU OUTPUT, check each why_it_matters against this list and rewrite if any fails.
These are the failures that actually happen; the prose above is context, this is the test:
  1. 30 words or fewer?  Count them.
  2. No "whether", "the real test", "remains to be seen", "will determine", "testing
     whether", "depends on"?  If an em dash is followed by a hedge, cut from the dash.
  3. No guess at intent, and no prediction of an outcome nobody has observed?
  4. Every number and comparison traceable to the material you were given?
  5. None of: capacity, machinery, underscores, highlights, signals, speaks to, rare,
     chronic, textbook?"""


RULES = """
HOW TO WRITE why_it_matters

Name something concrete from THIS event — the agency, the instrument, the dollar figure,
the deadline, the named program, the specific thing that changed — and tell the reader a
consequence the title and summary do not already state. A line that would fit fifty
other events is a failed line.

Do not restate or explain the competency. The reader can see the chip.

Some events are routine housekeeping whose whole point is already in the title, and
those tempt you into inflation. Do not inflate. Say the smallest true thing: who now has
to do what, what it replaces, who is affected. A modest, concrete line about a modest
event is correct.
""" + _COMMON


# Candidates are the mirror image. A blind round using the general rules above lost 8 of
# 10 candidate rows, because it stripped exactly what a candidate reader wants: where
# the action sits in the race, and what kind of governing action it is. But the fix
# overcorrected — lines that made the CAMPAIGN the subject lost too (0 of 4 winners
# framed it that way; 3 of 6 losers did). The substance is the subject; the race is a
# trailing clause.
CANDIDATE_RULES = """
HOW TO WRITE why_it_matters FOR A CANDIDATE DEVELOPMENT

The reader wants to know what this reveals about how this person would govern. So,
unlike the main tracker, you MAY name plainly what kind of governing action this is
("a direct workforce-training initiative", "an audit of school-choice spending") and you
MAY connect it to the candidate's record, their current office, or the session or cycle
it lands in.

THE SUBSTANCE IS THE SUBJECT, NOT THE CAMPAIGN. Lead with what actually happened and
what it does. The race may appear only as a trailing clause at the end of the sentence,
never as the sentence's subject or its purpose. Write "The enacted budget gives Hochul
direct control over $1.5 billion outside standard appropriations review, authority she
carries into her 2026 campaign" — never "gives Hochul a concrete administrative action
to run on in 2026". If the line would still stand with the race clause deleted, it is
built correctly.

NEVER use the phrase "first concrete", or the construction "gives him/her a record to
run on", "positioning his/her campaign", or "a concrete X to run on". These became a
verbal tic across a majority of generated lines and read as machine-written in a digest.

A pledge that is only a pledge is still worth describing accurately: say what it would
do, not whether it will happen.
""" + _COMMON
