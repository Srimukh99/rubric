# build

## Before starting

Read the whole plan, then check it against the repo as it is now:
`python3 skills/design/scripts/plan_check.py <plan> --red`. Raise every FAIL,
gap, wrong assumption or missing task now, not halfway through. If not
already isolated, use `references/sandbox.md`.

## Loop

For each task, in order:

1. Do the steps exactly as written: the test as given, the FAIL run (it must fail for the stated
   reason), then the code. `Produces` is the contract: same names, same parameters. `Mirrors` is the
   shape to copy. Follow `references/prove-it.md` for the code itself.
2. A task that takes more than one attempt runs under `ratchet`, with that task's test as its target.
3. Run the PASS command and read the output. Tick the step boxes as you go, then commit as the plan says.

After every 3 tasks, post a checkpoint: what changed, verify output, anything surprising. Continue only when the user says so, unless they asked you to run the whole plan.

## When reality differs

Stop and say so if a file, API or behaviour isn't what the plan assumed. Never quietly change the plan. Update the plan file with the change and the reason, then re-run `plan_check.py` on it: a change to one task's `Produces` breaks every task that consumes it, and the check lists them.

## Review as you go

After each task, `python3 skills/review/scripts/review_pack.py --base <task start> --plan <plan> --task N`
settles the facts in seconds: a planned interface missing, a test changed, a file outside the plan.
Fix its FAILs before the next task, while the code is fresh. The judgement review (`review`) runs on
the whole branch at the end.

## Done when

All tasks are ticked, `loop.py full` passes and `tamper.py` is clean. Next: `review`, then `ship`.
