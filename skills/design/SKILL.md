---
name: design
description: Use when an idea is still fuzzy, or asked to build a feature or change behaviour and nothing is specced yet, or when an approved design needs breaking into small tasks with exact files, tests and proof commands. Works out what to build before any code.
---

# design

Nothing is built until the user approves a design. Read only the part you need.

| Situation | Read |
| --- | --- |
| An idea to explore, a "could we…" question, or a request to build a feature, add behaviour or change how something works, before any code. Sizes the ask, finds the intent, and scales the design to it. | `references/shape.md` |
| A design is approved or a multi-step change needs a plan before coding. Breaks the work into small tasks with exact files, a test to write first, and a command that proves each task works. | `references/blueprint.md` |

Order: `references/shape.md`, then `references/blueprint.md` once a structural design is approved. A bounded change goes from its four-line design straight to `build`. Skip shape when a design already exists.

Script: `scripts/spec_check.py` (checks a design file for placeholders, missing sections and unmeasurable success before approval).
