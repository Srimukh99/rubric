# hunt

No fix until you can say what causes the bug and show it.

## 0. Read the evidence first

A log or stack trace goes through `log-trace` (or `log-fetch <service>` when
you have none) before any code is opened: it returns the error, the in-repo
source line and where the app runs, in about 20 lines. Then read the whole
error yourself: the exact message, the first frame in this repo, any code or
id. Most bugs are named in the first error, not the last.

## 1. Reproduce

The smallest reliable repro, with its exact command and output. Then sort it:

| It… | Run | What it tells you |
| --- | --- | --- |
| fails every time | the repro | a plain bug: go to step 2 |
| fails sometimes | `flake.py rate TEST -n 20` | the failure rate and its messages, before and after any fix |
| passes alone, fails in the suite | `flake.py polluter TEST` | the earlier test(s) leaking state into it, in about log2(n) runs |
| leaves a file or dir behind | `flake.py polluter --creates PATH` | which test creates it |
| fails on timing, under load or in CI only | `flake.py sleeps` | fixed waits that guess how long something takes |

A slow suite: add `-j 4` when its runs cannot collide on shared files, ports
or databases. Cannot reproduce it: collect more (logs, inputs, versions,
environment) and say so. Do not fix what you cannot see fail.

## 2. Narrow it

- **What changed**: `git log -p` on the failing path, `git bisect run <repro>`,
  dependency lockfile diffs, recent deploys, config and flags.
- **A working twin**: find the closest code in this repo that does the same
  thing and works. Read both in full and list every difference, however small.
  The bug is in that list.
- **Several parts** (CI → build → deploy, API → service → database): log what
  enters and leaves each boundary, with the config each one sees, and run it
  once. The first boundary where the data or config is wrong is the part to
  open. Log ids and shapes, never secrets or personal data.
- **A bad value far from its source**: `references/trace-back.md`.
- Halve the search space each step.

## 3. Explain it

Keep a visible ledger, one line per hypothesis:

```text
H1  X causes Y because Z     test: <smallest experiment>     result: confirmed | ruled out
```

Change one variable per experiment. A ruled-out hypothesis stays in the ledger
so it is not tried twice. When you do not know, write "I don't understand X
yet" and go get the evidence, rather than writing a guess as a cause.

## 4. Fix it

A failing test that reproduces the bug first (`build`). Fix the cause where it
starts, not where it shows. One change; no "while I'm here" edits riding along.

## 5. Confirm it

The repro passes, the full suite is green, and a flaky test shows
`flake.py rate TEST -n 20` at 0 failures, where it showed some before (`ship`).

## Three strikes

A fix that needs more than one attempt goes under `ratchet`, with the repro
test as its target, so the count is kept by a script, not by memory. Its STOP
after three attempts that did not help is the stop: revert, and tell the user
what was tried, what each result showed, and what you now believe.

Three failed fixes usually mean the design, not the bug: each fix moves the
failure somewhere new, or needs a wide refactor to land. Say that, and agree
the next step with the user before a fourth attempt.

## When there is no single cause

Timing, the environment or another system, and you can show it: write down
what was ruled out and how, handle it explicitly (a bounded retry, a timeout,
a clear error), and add a log or metric that would catch it next time. Check
first that this is not just an investigation that stopped early: name the
hypothesis you have not tested.

## Guessing, and what is true instead

| The thought | What is true |
| --- | --- |
| "I see it, let me just fix it" | Seeing the symptom is not knowing the cause. Write the hypothesis and test it |
| "Try X and see if it works" | That is a guess with a deploy attached. One hypothesis, one experiment |
| "Change a few things, then run the tests" | Then nothing can tell you which change mattered |
| "Fix now, investigate later" | Later never comes, and the guess becomes the design |
| "It's simple, it doesn't need the process" | Simple bugs go through it in minutes |
| "One more attempt" after two failures | That is strike three. Stop and look at the design |
| "Skip the test, I checked it by hand" | A fix with no failing test first comes back |
| "It's flaky, add a retry" | A retry hides the race. Measure the rate, find the cause |

When the user says "stop guessing", "did you check…", or "we're going in
circles", go back to step 1.

## Production incidents

Mitigate first (roll back, disable the flag, scale up), then hunt.
