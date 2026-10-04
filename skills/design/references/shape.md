# shape

Goal: agree on what problem this is, then what to build, at the weight the
change deserves, before building it.

## 1. Size the ask first

Read the relevant code, docs and recent commits, then sort the ask and say
which in one line, with the signal that decided it. The user can overrule.

| Size | Signals | What it gets |
| --- | --- | --- |
| **Probe** | A question or a "could we…": no user, outcome or shape yet | Talk it through. A throwaway prototype may answer a question; it is deleted, never merged. Ends in findings and a recommendation, or a promotion to bounded or structural |
| **Bounded** | One component, behaviour already clear, nothing below changes, a revert undoes it | Steps 2–3 briefly, then a four-line design in the reply. One yes. No file |
| **Structural** | Any one of: a new service or module boundary; a schema or data migration; a public API or contract; a new dependency or vendor; auth, money or regulated data; more than one team or service; anything a revert cannot undo | Every step below, a design file, the self-check, and approval of that file |

One structural signal is enough. In doubt, size up. Re-size the moment an
answer uncovers a signal: "just a retry" that needs a new queue is structural.

## 2. Find the intent before any approach

Ask only what the repo cannot answer, one question per message, multiple
choice when possible. In this order, skipping what is already clear:

1. **Problem**: what goes wrong today, and for whom? Not the fix they asked for.
2. **Success**: how will anyone know it worked? A number, a behaviour, a test.
3. **Bounds**: what is explicitly out, and any deadline or budget.
4. **Fixed points**: what must not change.

A request that names a solution ("add a retry") gets restated as the problem
behind it ("calls to the billing API fail about 2% of the time and the user
sees an error"). The approaches may then include not building it.

Stop asking once a paragraph covering problem, user, success and non-goals
gets a yes. More than five questions on a bounded change means it was sized
wrong, or the questions are ones the code could have answered.

## 3. Offer approaches

2–3, including the smallest that could work, and "don't build it" when that is
real. For each: complexity, risk, cost, how hard it is to undo. Recommend one
and say why. For a probe, the approaches are experiments: what each would
show, and what it costs to find out.

When a choice is easier to see than to read (a layout, a flow, where a
component sits), sketch the options side by side in ASCII or Mermaid and ask
which.

## 4. Write the design at its size

**Bounded**, in the reply:

```text
Problem: <one line>
Change:  <files or components, and what changes in each>
Proof:   <the test that fails now and passes after>
Undo:    <how to back it out>
```

**Structural**, in `docs/designs/YYYY-MM-DD-<topic>.md`, presented section by
section with a yes on each:

```text
# <title>
Size: structural
Status: draft
## Problem
## Success
## Non-goals
## Approaches considered
## Data model
## Interfaces
## Flow
## Failure modes
## Testing
## Rollout and undo
## Open questions
```

Draw what has three or more moving parts, or states: a Mermaid sequence or
state diagram in the file beats a paragraph nobody can check.

## 5. Check the design before asking for approval

Structural designs only. Run:

`python3 <this skill folder>/scripts/spec_check.py docs/designs/<file>.md`

It FAILs on placeholders left in (TBD, TODO, `???`, an unfilled `<slot>`),
missing or empty sections, a success line with nothing to measure, a rollout
with no way back, and open questions with no owner. Then read the file once
for what a script cannot see:

- **Contradictions**: a non-goal that the flow quietly does; one field with
  two types; a flow step no interface supports.
- **Coverage**: every failure mode has a test, or a stated reason it cannot.
- **Undefined terms**: anything used before it is defined.
- **The success line**: would two people measuring it get the same answer?

Fix, re-run until clean, then ask for approval of the file. Record it on the
status line, `Status: approved by <name> on <date>`, and the check holds it to
having no open question left.

## Flag early

Anything touching regulated data, money movement, auth or external systems
changes the design, and makes it structural (see `reg-*`, `review`).

## Keep it lean

- Cut anything the stated goal doesn't need.
- Prefer tech already in the repo over new dependencies.
- Make the first version small enough to ship and measure.

## Done when

- **Probe**: the findings and a recommendation are agreed, or it was promoted.
- **Bounded**: the user said yes to the four lines. Next: `build`.
- **Structural**: `spec_check.py` is clean and the status line records
  approval. Next: `references/blueprint.md`.
