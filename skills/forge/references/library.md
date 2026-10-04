# library

Adding a skill to rubric itself, or editing one. Everything in
`references/write.md` and `references/test.md` applies; these are the
library's own rules on top.

## Where it goes

- A new job inside an existing skill is a `references/` file in that skill,
  with a row in its `SKILL.md` table. Core stays at 14 skills.
- A specialist skill goes in a pack, `packs/NAME/skills/`, with a pack prefix
  (`pg-`, `mongo-`, `snow-`, `dbx-`, `api-`, `agent-`, `reg-`).
- Folder name equals `name`: lowercase kebab-case, 20 characters or fewer.

## Format

- `SKILL.md`: the description, one line on what it is for, a table of
  situations each pointing at one `references/` file, an order line, and the
  scripts it carries. Under 200 lines.
- Each reference does one job and ends with **Done when**. Scripts are stdlib
  only, print a short summary and exit non-zero on FAIL.
- No agent-specific tool names; original wording only.

## Prove it here

1. Add 3 prompts that should reach the skill and 2 near-misses that should not
   to `evals/skill_triggers.json`. Never copy from the held-out routing set.
2. `python3 skills/forge/scripts/skill_check.py` (no path) checks every changed
   skill in the library: triggers, and every dev and legacy routing case that
   your change breaks against the base, plus the always-loaded token change.
3. Run `python3 evals/routing.py --held-out` once, at the end. Never edit to
   improve it; a set you tune on stops measuring.
4. `python3 tools/lint_skills.py`, `python3 tools/check_layout.py`, and a row in
   the `boot` routing table.

Measured here: deleting the "what it does" sentences from seven descriptions
cut dev routing from 98% to 88%, because they carried trigger words;
rewriting them to fit the dev set cost held-out part routing 85% to 77%. Keep
the words, as conditions, and let the check decide.

## Done when

`skill_check.py`, lint and layout are clean, held-out routing is no worse,
`boot` lists the skill, and its behaviour is tested or reported as not run.
