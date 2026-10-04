---
name: forge
description: Use when creating a new rubric skill or editing an existing one.
---

# forge

A skill is guidance an agent loads by its description, then follows when no one
is checking. Build it the way the library builds code: decide what it is, write
it against an observed failure, and prove it by measurement.

## What it should be

- **A rule a script can check** is a script, in the skill's `scripts/` or in a
  gate. Prose is for judgement.
- **A fact about one project** goes in that project's `AGENTS.md`, not here.
- **A technique or rule that holds across projects and is not obvious** is a
  skill, or a reference inside the skill whose job it extends. Core stays at
  14 skills; a specialist skill goes in a pack under `packs/NAME/skills/`.

## Format, as the library already uses it

- Folder name equals `name`: lowercase kebab-case, 20 characters or fewer, pack
  prefix for domain skills (`pg-`, `mongo-`, `snow-`, `dbx-`, `api-`, `agent-`, `reg-`).
- `SKILL.md`: the description, one line on what the skill is for, a table of
  situations each pointing at one `references/` file, an order line, and the
  scripts it carries. Under 200 lines.
- Each reference does one job, in imperative steps, and ends with **Done when**.
- Scripts are stdlib only, print a short summary, exit non-zero on FAIL, and
  are named in the skill's own text so an agent can find them.
- No agent-specific tool names: say "run the tests", "search the repo".
- Original wording only.

## The description

It is read in every session to decide whether to open the skill, so it is a
condition, not a summary:

- Start with "Use when", and use the words people type: symptoms, error text,
  tool and product names, the synonyms they reach for.
- Third person; about 40 words. Every word loads on every request.
- A sentence saying what the skill does can become a shortcut an agent follows
  instead of reading the skill. Recast it as a condition, keeping its trigger
  words. Measured here: deleting such sentences outright cut dev routing from
  98% to 88%; recasting them kept it.

## Match the form to the failure

Watch the failure first (see below), then choose the form:

| What the agent did | What fixes it |
| --- | --- |
| Skipped a rule it knew, under pressure | The rule, the phrases that signal the skip, an excuse-and-reality table, and a script for whatever can be enforced |
| Right content, wrong shape | A template with fixed slots in order |
| Left out a required part | A required field or section, checked by a script |
| Acted when it should not, or not when it should | A condition the agent can observe ("when the plan has a `Design:` line") |

No "unless it matters" clauses and no exemption clauses: each reopens the
negotiation the rule was written to close.

## Prove it

1. **Triggers.** Add 3 prompts that should reach the skill and 2 near-misses
   that should not to `evals/skill_triggers.json`, phrased as a user would.
   Never copy from the held-out routing set.
2. **Check.** `python3 skills/forge/scripts/skill_check.py` checks every changed
   skill: it FAILs a misrouted trigger, any dev or legacy routing case that was
   right before your change and is wrong after it, and an agent-specific tool
   name; it WARNs on length and on "what it does" sentences, and reports the
   change in always-loaded tokens.
3. **Behaviour.** Write 3 tasks that tempt the shortcut the skill exists to
   stop: time pressure, work already sunk, "it's only small". Run them without
   the skill and record what the agent did and the exact excuse it gave. Write
   the skill against those, run them with it, and turn each new excuse into a
   row. Where agents cannot be run, say behaviour is unverified.
4. **Held-out.** Run `python3 evals/routing.py --held-out` once, at the end.
   Never edit anything to improve it; a set you tune on stops measuring.
5. `python3 tools/lint_skills.py` and `python3 tools/check_layout.py`, and add
   the skill to the `boot` routing table.

## Done when

`skill_check.py`, lint and layout are clean, held-out routing is no worse,
`boot` lists the skill, and its behaviour is proven or reported as unverified.
