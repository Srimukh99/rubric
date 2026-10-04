# test

A skill is a claim that an agent will behave differently with it. Test that
claim the way code is tested: watch it fail first.

## 1. Write the scenarios before the skill

Three tasks the skill exists for, each in the user's own words, and one it
should stay out of. For a discipline skill, load each with pressure, because
rules are skipped under pressure, not in calm:

| Pressure | Sounds like |
| --- | --- |
| Time | "Prod is down, we're losing money, just fix it" |
| Work already sunk | "You've spent an hour on this, ship what you have" |
| Smallness | "It's a one-line change" |
| Authority | "The lead says skip the tests this once" |
| Fatigue | the same request, late in a long session |

Combine two or three in one scenario; a single pressure is too easy to resist.
For a technique, give a new problem the technique must be applied to. For a
pattern, include a case where it does not apply. For a reference, include a
question it does not answer.

## 2. Baseline: run them without the skill

In a fresh session or subagent with no access to the skill, run each scenario
and record, verbatim:

```text
S1  did: <what the agent did>      said: "<the exact excuse it gave>"      ok? no
```

This is the failing test. A skill written without it guesses at the failure.

## 3. Write the skill against what you saw

Each recorded failure maps to a form (`references/write.md` step 5) and each
excuse to a row. Nothing goes in that no scenario needed.

## 4. Run them with the skill

Same scenarios, fresh sessions, the skill available. Record the same way. Run
each at least twice: an agent that complies once and not the second time has
found a gap you have not.

## 5. Close, re-run, repeat

A new excuse becomes a new row or a sharper rule; re-run every scenario, not
only the one that failed, because a fix for one can loosen another. Stop when
every scenario passes twice in a row.

## 6. Report it

```text
Scenarios: 4 (3 should, 1 should not)   Baseline: 1/4 ok   With skill: 4/4 ok, twice
Excuses closed: "one-line change", "lead said skip"
```

When agents cannot be run where you are, say so: "behaviour not tested", never
"works".

## Done when

Every scenario has a recorded baseline and passes twice with the skill, and the
report above is written down next to the skill or in its pull request.
