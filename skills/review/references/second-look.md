# second-look

An independent review of a finished change. Two passes: a script settles every
fact it can, then a reviewer judges what is left.

## 1. Pack it

```text
python3 <this skill folder>/scripts/review_pack.py --plan docs/plans/<plan>.md [--task N]
```

It writes one file: the mechanical findings on top (planned files untouched or
unplanned files changed, a planned interface missing or with other
parameters, a plan's test missing, renamed or changed, a secret or debug
leftover, a test skipped or weakened), then the tasks in scope with their
contracts, the commits, and the diff with context. Fix its FAILs before
spending a reviewer: they are facts, not opinions. Without a plan, it still
runs the gates. `--task N` reviews one task's range; the whole branch gets
one more review at the end.

## 2. Brief the reviewer

If your agent can start a subagent, give a fresh one the package path, the
plan or requirements path, and the project-wide constraints copied verbatim.
Nothing from your own conversation: the reviewer judges the work, not your
reasoning about it. Without subagents, do the pass yourself after a break in
context, reading the package as if a stranger wrote it. The reviewer:

- reads every hunk, and does not write "looks good" about code it did not read;
- changes nothing: no edits, no checkout, no commits on this branch;
- does the review itself, in passes if the diff is large, and starts no reviewers of its own;
- does not re-run tests the package already reports.

## 3. What to judge

- **The requirement, as a user would read it.** The plan says what the code
  must do, not every input it will meet. Where it is silent, what a
  reasonable user would expect is the requirement: an empty list, a retry
  that never ends, a timeout nobody set.
- **The design**: one purpose per unit, interfaces that hide their insides,
  the existing pattern followed (`design` "Design the units"), and no cleanup
  beyond what the change needed.
- **Tests**: they check behaviour through the interface, cover the plan's
  failure modes and the boundaries in `build`'s `references/prove-it.md`,
  and would fail if the code were wrong.
- **Errors, data and operations**: nothing swallowed; no secrets or regulated
  data in code, logs or fixtures; no N+1 queries or unbounded loads;
  migrations safe on live data (`pg-migrate`); logs and metrics for anything
  new; security-sensitive paths through `references/threat-check.md`.

## 4. Report

```text
Verdict: ready | ready after fixes | not ready - <one line why>
Blocker   file:line  what is wrong  ->  why it matters  ->  the fix
Should fix ...
Nit        ...
Set aside: <behaviour considered and not judged, and why>     (one line each; "none" if none)
Cannot verify from the diff: <requirement that lives in unchanged code or another task>
Done well: <one or two specifics, so the rest reads as calibrated>
```

Severity is the effect on a user or on the next change, not on taste. A
finding with no file and line, or no fix, is not finished.

## 5. After the review

Blockers and Should-fixes go back to the author, judged with
`references/weigh-in.md`. Re-run `review_pack.py` on the fix range, and
re-review only the fix and the findings it claims to close. Nits and the
"set aside" lines go into the final branch review, not into this loop.
