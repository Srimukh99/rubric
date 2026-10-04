# blueprint

A plan is every decision the person executing it could not make alone:
which files, which names and signatures, which values, which test proves
each step. Write it for someone who has never seen this codebase or this
conversation, and who will do exactly what it says. They write good code once
they know the interface and the test; what they cannot know is what was
decided. For a bounded change, the four-line design from `references/shape.md`
is the plan; skip this file.

## Before any task: the file map

List every file the work creates or changes, and what each one is for. This
is where the design's units become files, so apply `references/shape.md`
"Design the units" here: one purpose per file, split by responsibility, not
by layer; files that change together live together; follow the shape of the
nearest existing code. A file you must edit that has grown unwieldy may be
split as its own first task. Nothing else gets refactored.

## The format

`plan_check.py` reads this format, so keep the field names and the order.

````text
# <feature>: plan

Design: docs/designs/YYYY-MM-DD-<topic>.md
Goal: <one sentence>
Approach: <two or three sentences>
Stack: <language, framework, test runner, versions that matter>

## Constraints
- <a project-wide rule, with its exact value from the design>

## File map
| File | Change | Responsibility |
| --- | --- | --- |
| src/billing/retry.py | create | the backoff schedule and the retry loop |
| src/billing/client.py | modify | wraps charge() in the retry loop |
| tests/test_retry.py | create | retry behaviour, against a fake billing API |

## Task 1: Backoff schedule
Covers: Success 1, Failure modes 1
Files: create src/billing/retry.py; create tests/test_retry.py
Mirrors: src/billing/http.py
Consumes: none
Produces: `backoff(attempt: int) -> float`

- [ ] Write the failing test in tests/test_retry.py:
```python
from billing.retry import backoff

def test_backoff_doubles_and_caps():
    assert [backoff(n) for n in (1, 2, 3, 9)] == [0.2, 0.4, 0.8, 5.0]
```
- [ ] Run `pytest tests/test_retry.py -q`. Expect FAIL: `cannot import name 'backoff'`
- [ ] Implement `backoff(attempt: int) -> float` in src/billing/retry.py: 0.2 s doubled per attempt, capped at 5.0.
- [ ] Run `pytest tests/test_retry.py -q`. Expect PASS
- [ ] Commit: `git add src/billing/retry.py tests/test_retry.py && git commit -m "Add the billing backoff schedule"`
````

| Field | What it carries |
| --- | --- |
| `Covers` | Which design lines this task makes true: `Success 2`, `Failure modes 3`. Every one of them is covered somewhere |
| `Files` | `create`, `modify` (optionally `path:120-145`) or `test`, separated by `;` |
| `Mirrors` | Optional. Existing code whose shape to copy: the cheapest way to follow the repo's patterns |
| `Consumes` | What this task uses from earlier tasks or the repo, as signatures, or `none` |
| `Produces` | What later tasks rely on, as exact signatures: name, parameters, return type |
| `[parallel]` | After the task title, when it shares no file with, and consumes nothing from, other `[parallel]` tasks |

## What a step contains

Enough that there is exactly one reasonable thing to write, and no more:

- **Test step**: the test as code, with the design's exact values in it.
- **Run step**: the command, and the result that means it worked. A FAIL
  names its reason, so a test failing for the wrong reason is visible.
- **Implement step**: the signature, the file, and one line on any choice the
  signature and test leave open. A body only for an algorithm they do not
  determine, or copy the design fixes word for word. A plan longer than the
  code it describes has written the code instead.
- **Another task's work**: named through its `Produces`, never repeated.

Lines that decide nothing are gaps: "handle edge cases", "add appropriate
validation", "write tests for the above", "similar to task 3", a name no task
produces. The design's edge cases and failure modes get their own test steps
in the task that owns the code (see the boundary table in `build`'s
`references/prove-it.md`).

## Sizing and order

- A task is the smallest change with its own test cycle that a reviewer could
  accept while rejecting its neighbour. Setup, config and docs fold into the
  task that needs them.
- Steps are a few minutes each. A task over about six steps is two tasks.
- Riskiest and least certain first, so a surprise costs the least rework.
- Migration, config, observability and `reg-*` checks are tasks, not notes.

## Check it, then prove the tests are red

```text
python3 <this skill folder>/scripts/plan_check.py docs/plans/<file>.md
python3 <this skill folder>/scripts/plan_check.py docs/plans/<file>.md --red
```

The first reads the plan against the repo and the design. It FAILs on a
missing field, a placeholder, a `Consumes` no earlier task produces and the
repo does not define, the same name with different parameters in two tasks,
a `modify` path that does not exist or a `create` path that does, a task that
needs a later one, `[parallel]` tasks sharing a file, a design line no task
covers, and test code that does not parse. It WARNs on an implement step that
is mostly code.

`--red` runs the plan's own commands in a scratch checkout, writing each
task's test before running it, and FAILs any test that passes before its code
exists: a test that is green on day one checks nothing. It runs commands from
the plan, so read the plan before running it on a repo you do not control.

`--waves` prints which tasks can run at once, for `delegate`.

## Done when

`plan_check.py` and `--red` are clean, and the user approved the plan. Save it
to `docs/plans/YYYY-MM-DD-<topic>.md`. Next: `build` (each task's test is its
`ratchet` target), or `delegate` for the waves.
