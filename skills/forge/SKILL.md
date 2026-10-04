---
name: forge
description: Use when writing, creating or editing a skill (a SKILL.md) for any agent or project, when a skill does not trigger or an agent ignores it under pressure, or when adding a skill to the rubric library.
---

# forge

Build a skill the way code is built: decide what it is, watch the failure it
must fix, write against that, and prove it. Read only the part you need.

| Situation | Read |
| --- | --- |
| Writing or editing any skill, for any agent or project: what it should be, its type, the description, the body, the form that fits the failure, closing loopholes. | `references/write.md` |
| Proving a skill changes behaviour: scenarios with pressure, a baseline without the skill, the run with it, and closing the gaps it shows. | `references/test.md` |
| Adding or editing a skill in the rubric library itself: where it goes, its format, triggers and routing checks. | `references/library.md` |

Order: `references/write.md` and `references/test.md` together (write the
scenarios first), then `references/library.md` only inside rubric.

Script: `scripts/skill_check.py` (lints any skill folder and routes its trigger prompts; `new` scaffolds one by type; inside rubric it also guards the library's routing).
