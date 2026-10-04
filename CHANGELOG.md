# Changelog

## 0.8.0
- `forge` now writes any skill, for any agent or project, not only rubric's.
  `references/write.md`: decide whether it is a script, an `AGENTS.md` line or a
  skill; its type (discipline, technique, pattern, reference), each written
  and tested differently; the description as a condition, with weak and strong
  examples; the body; the form that fits the observed failure; closing the
  loopholes a tested agent found. `references/test.md`: pressure scenarios
  written first, a baseline without the skill, runs with it, twice, and a
  report. `references/library.md`: rubric's own rules on top.
- New script, `forge/scripts/skill_check.py`. On any skill folder, anywhere:
  name and folder, the description, length, links to files that exist,
  scripts it names, placeholders, "Done when", and with `--triggers` the
  prompts routed against the skills beside it (top pick or FAIL). A
  planted-defect comparison against a written skill-authoring checklist found
  four gaps, all now FAIL: a workflow inside the description, a "what it
  does" sentence, a clause that reopens a rule ("unless it matters"), and a
  hard rule with no excuse table, red flags or baseline. Inside rubric only
  new violations FAIL; ones a skill already had stay WARN. `new NAME
  --type T` scaffolds a skill whose slots FAIL the check until filled. Inside
  rubric it also routes each changed skill's
  trigger prompts from the new `evals/skill_triggers.json` (3 should, 2 should
  not, all 28 skills), FAILs any dev or legacy routing case a change breaks
  against the base, flags agent-specific tool names, WARNs on length and on
  "what it does" sentences, and reports the always-loaded token change. CI runs
  it on every skill.
- Measured, then decided: deleting the "what it does" sentence from seven
  descriptions saved 14% of always-loaded tokens but cut dev routing from 98% to
  88%; recast as conditions it reached 100% on dev, and the one held-out run
  showed part routing falling from 85% to 77%. That was fitting the dev set, so
  every one of those edits was reverted. The 140 new trigger prompts then found
  two real misroutes and two weak ranks; four small edits fixed them, dev top-1
  98% to 100%, legacy 100%, held-out top-1 unchanged and top-3 90% to 93%, for
  14 more always-loaded tokens.
- Review settles the facts before anyone reads the diff. New script,
  `review/scripts/review_pack.py`: with the plan, it checks every planned file
  changed and nothing else, every planned interface defined at HEAD with the
  planned parameters, and every test the plan wrote still there and unchanged
  (compared as syntax, so reformatting is not a change); it runs `vibe_check`
  and `tamper` over the range; and it writes one file with those findings on
  top, then the tasks in scope, the commits and the diff. Range guards refuse
  an empty range or a base that is not an ancestor.
- `second-look.md` is now a brief for an independent reviewer: package path,
  plan and constraints only; read every hunk; change nothing; spawn no
  reviewers; judge silence in the plan by what a reasonable user expects;
  report a verdict, findings with file, line, why and fix, what was set aside,
  and what the diff cannot show. `weigh-in.md` reads every comment before
  acting, asks about the unclear ones first, checks "do it properly" against
  real callers, and replies with the change, not with agreement.
- `delegate` reviews each worker before it lands: the package first (its
  FAILs go back without spending a reviewer), then a capped fix loop - two
  rounds with the same worker, a third with a fresh one, then a ruling on
  each open finding, written to `.rubric/ledger.md`. `build` runs the package
  after every task.
- New eval, `evals/review_eval.py`: the plan_eval fixture, implemented cold.
  The clean range gives no findings; 9 of 9 planted implementation defects
  are named before a reviewer reads the diff.
- `design/references/blueprint.md` is now a plan someone who has never seen the
  repo can execute, not interpret: a file map with one responsibility per
  file, then tasks that carry what they cover in the design, their files, the
  existing code to mirror, the exact signatures they consume and produce, the
  failing test as code, the command with the reason it must fail, the
  signature to implement, the passing run and the commit.
- New script, `design/scripts/plan_check.py`, does mechanically what a plan
  review otherwise asks a model to remember: every consumed name produced by
  an earlier task or defined in the repo, with the same parameters (and a
  "did you mean" for a typo); `modify` paths that exist and `create` paths
  that do not; no task needing a later one; every Success and Failure-modes
  line of the design covered; `[parallel]` tasks that share nothing; no step
  that decides nothing; test code that parses. `--red` copies the working
  tree, writes each task's test and runs the plan's own FAIL command, failing
  any test that is green before its code exists. `--waves` hands `delegate`
  the tasks that can run at once. `build` runs it before executing a plan and
  after any change to one.
- `shape.md` gains "Design the units": one purpose each, an interface stated
  without the internals, testable alone, the nearest existing pattern
  followed, and only the cleanup this change needs.
- New eval, `evals/plan_eval.py`: 19 defects a cold executor would hit,
  planted one at a time in a real plan, all caught for their own reason; the
  clean plan passes, its tests are proven red, and executed cold every PASS
  command passes.
- `design` now starts before the ask is a feature. `shape.md` sizes it first -
  probe, bounded or structural, on named signals (a schema change, a public
  API, a new dependency, money or auth, anything a revert cannot undo) - and
  scales the work to it: a probe gets a conversation and a throwaway
  prototype, a bounded change a four-line design approved in the reply, a
  structural change a design file. Before any approach it finds the intent one
  question at a time - problem, success, bounds, fixed points - and restates a
  request that names a solution as the problem behind it, so "don't build it"
  can be an option. Its write-back keeps "you said" apart from "I'm assuming",
  and nothing assumed counts as agreed until the user has seen it. An ask
  holding several independent parts is split before any detail question; a
  new project is never bounded; sizes only go up mid-task; and one yes
  approves one stage, not the documents that follow it.
- New reference, `design/references/sketch.md`: when a question is easier to
  see than read, and which Mermaid diagram answers it - options side by side,
  calls in order with the failure path, states, data - with an ASCII sketch
  for screen layouts. Every example renders in the real Mermaid renderer.
- New script, `design/scripts/spec_check.py`: checks a design file before
  approval for placeholders, missing or empty sections, success lines with
  nothing to measure, a rollout with no way back, open questions with no owner,
  an approval that leaves a question open, and Mermaid that will not render or
  will not draw what was written. It warns on wording that reads two ways
  ("etc.", "and/or", "gracefully") and on a structural design with no diagram.
  Against the real renderer, on 28 diagrams (the examples and mutations of
  them), the lint missed none of the 18 broken ones; it also fails two that
  Mermaid accepts, both `[* --> a`, which Mermaid draws as a box labelled "[*". What a script cannot see -
  contradictions, untested failure modes, terms used before they are defined -
  is a checklist in `shape.md`. Routing is unchanged (dev 98% top-1, legacy
  100%); always-loaded text grew 7 tokens.
- `debug/references/hunt.md` goes deeper where guessing starts: read the whole
  error first; sort the repro (fails always, sometimes, only in the suite, only
  on timing) and send each to the command that answers it; find a working twin
  in the repo and list every difference; log each boundary once in a system of
  several parts; keep a hypothesis ledger with ruled-out entries; count fix
  attempts with `ratchet` so three strikes is kept by a script, not memory;
  say when the design is the problem; handle "no single cause" without
  stopping early; and a table of the thoughts that start a guess-and-patch
  loop, with what is true instead.
- New script, `debug/scripts/flake.py`. `rate` reruns a test alone and reports
  how often it fails and with which messages. `polluter` finds the earlier
  test(s) that break a test only in the suite, or that leave a file behind, by
  binary search over the suite's own order with delta debugging as the
  fallback: about log2(n) runs per culprit, and a pair that only breaks the
  victim together is still found. `sleeps` lists fixed waits in test files.
  pytest and unittest are detected; `--cmd` takes any runner. New eval,
  `evals/flake_finder.py`: right on 75 of 75 cases in 544 runs, against 60 of
  75 in 4,950 for trying earlier tests one at a time.
- `ship/references/receipts.md` now covers the claim itself, not only the proof:
  a list of phrases that mean the command has not been run ("should work",
  "looks right", "I'm confident"), an excuse-and-reality table for the nine
  reasons a check gets skipped, a delegation row that sends you to the VCS diff
  instead of a subagent's report, and a requirements checklist built from the
  original request rather than from memory of it.
- New: `vibe_check.py --stop-hook`, a gate for the end of an agent turn. It scans the uncommitted work - staged, unstaged **and**
  new untracked files, where a just-created secret hides - reports on stderr
  because that is the only stream handed back to an agent, and exits 2 so the
  turn returns with the findings instead of ending on an unproven claim. It
  stands down on `stop_hook_active`, so it blocks once rather than looping. It
  also reads the agent's closing message from the transcript and FAILs on the
  `receipts.md` red-flag words ("should work", "I'm confident") outside quotes
  and code; a test keeps the script's list and the prose list identical. A
  second message check reads actions, not wording: success reported in any
  words ("Done!", "ready to merge") FAILs unless a check ran after the last
  edit and passed. Edits include shell writes; edits outside the repo do not
  count. `--no-claim-check` turns both off.
- `receipts.md` closes three gaps: rewording a prediction or celebrating
  ("Done!") is still a claim; a regression test counts only once it has been
  seen failing with the fix backed out (also in `build/references/prove-it.md`);
  and new excuse rows for a partial check and the last step of a task.
  `--install-stop-hook` merges it into `.claude/settings.json` without touching
  hooks already there, `--uncommitted` exposes the new scope on its own, and
  this repo ships its own hook in `.claude/settings.json` with a `make check`
  target for it to run.
- `--full` no longer crashes or lies when a detected command is missing: a tool
  that is not installed prints `SKIP`, not `PASS`, and a failing check's output
  is echoed into the hook's stderr rather than streamed to a stdout no agent
  reads.
- New eval, `evals/claim_guard.py`: turns that end in a claim with no receipt.
  The Stop hook, run for real, stops 16 of 19, and 9 of the 12 cases written
  before its message checks; it blocks 0 of 6 honest closings and 0 of 12 real
  closing messages replayed from the session that built it. Three claims no
  script can see remain, and the naming score is read as a floor, since the
  cases and the guidance were written together.
- Renamed from overmind to **rubric**. Four separate projects over 500 stars
  already shared the old name, including a 3,747-star Procfile manager. Project
  state moves from `.overmind/` to `.rubric/`, checkpoints from
  `refs/overmind/` to `refs/rubric/`, delegate worktrees from
  `REPO.overmind-team/` to `REPO.rubric-team/`, and the Claude plugins from
  `overmind*` to `rubric*`. Existing users: `git mv .overmind .rubric` and
  `git update-ref` the ratchet refs, or start a fresh ratchet. `evals/v05_descriptions.json`
  keeps the old name because it is a frozen baseline; routing is unaffected
  (dev 98% top-1, legacy triggers 100%).
- **`vibe_check.py` was a no-op outside this repo.** It pinned its scan target to
  its own install directory, so running it from any project reported
  `0 FAIL, 0 WARN, 0 lines scanned` and exit 0 without reading the staged diff.
  It now takes `--repo` (default: the current directory). Two integration tests
  that passed vacuously under the old behaviour now assert on scan output.
- A leftover `breakpoint()` no longer stalls a runner. `loop.py`, `ratchet.py`
  and `mutate.py` pass `PYTHONBREAKPOINT=0` to the child, so the suite reports
  instead of blocking on pdb until the timeout. Measured: 600s default timeout
  down to 0.1s on the reproduction. The gate still FAILs the leftover.
- Always-loaded descriptions cut 25%, 912 to 683 tokens, while routing improved:
  dev top-1 93% to 98%, top-3 98% to 100%, held-out 73% to 76%, legacy 100%.
- The evals could not run on an Apple Silicon Mac with an x86_64 Python, because
  git's xcrun shim cannot load into an x86 process. `evals/_eval_git.py` carries
  the `arch -arm64` fallback the skill scripts already had. All five now run in CI.
- New eval, `evals/code_quality.py`: three tasks with a visible suite and a
  withheld acceptance suite. 6 of 6 candidates pass their own tests, 3 are wrong,
  10 hidden defects would ship. It also found that **mutation score does not
  predict correctness across implementations and here is anti-correlated** (thin
  83%, solid 62%) - it measures whether a suite is real, not whether code is right.
- New eval, `evals/guidance_coverage.py`: whether the advice given when tests are
  written names the defect classes that actually ship. rubric 6/6 core, 2/4
  extended, 10/10 defects reachable; superpowers 2/6, 1/4, 3/10.
- `build/references/prove-it.md` gains a "Boundaries worth a test" table - nine
  classes, each with the question to ask and the bug it catches - and `Done when`
  requires it. It also states that `loop.py mutate` is not a substitute.

## 0.7.0
- `service_map.py --okf` exports the service map as an Open Knowledge Format (OKF v0.1) bundle: one typed document per service, cluster and log shipper, linked, with `index.md` files and a newest-first `log.md`. Only generated files are rewritten or pruned. `okf.py check` validates any bundle. Clusters are now recorded as clusters, not services.
- Installer: `--agent qwen` (Qwen Code) and `--agent cursor`; `all` now includes Qwen Code. README lists which agent reads which folder.
- Renamed from lockin to overmind. Project state now lives in `.overmind/`, checkpoints under `refs/overmind/`, worktrees in `REPO.overmind-team/`.
- `delegate` becomes contract-first, with a new `team.py`. The lead writes the shared contract, assigns each worker files no one else may touch, and `team.py check` rejects overlapping ownership, owned contracts and double-assigned targets before any work starts. Each worker gets its own git worktree and `ratchet`, all from one snapshot. `verify` compares each worker's claim with its ratchet verdict and flags false claims. `integrate` merges only verified workers in a scratch worktree, runs the suite once, and `--apply` lands it. Work proceeds in waves.
- `ratchet` checkpoints now use one ref namespace per working folder, so parallel ratchets in worktrees never overwrite each other.
- `evals/delegation.py`: five scripted workers, four with typical mistakes. Original contract tests passing at the end: trust the claims 2 of 8, the old delegate rules 7 of 8, contract-first 8 of 8. Bad changes that landed: 4, 1, 0.

## 0.6.0
- 41 skills become 14 core skills plus four optional packs. Related skills merged: `design` (shape, blueprint), `build` (build, prove-it, sandbox), `debug` (hunt, trace-back, log-trace, log-fetch), `review` (second-look, weigh-in, threat-check), `ship` (vibe-check, receipts, land, preflight, ship), `observe` (observe, slo). Each opens with a short table and points to one `references/` file, so the agent reads only what it needs.
- Nothing deleted. 19 instruction files moved with 24 of about 410 lines updated (skill-name and path references only). All 14 scripts are unchanged except two path lookups.
- Packs: `regulated` (reg-phi, reg-pci, reg-money, reg-audit), `data` (pg-explain, pg-migrate, mongo-index, snow-perf, dbx-perf), `k8s` (k8s-triage, drift, crd-check), `apis-agents` (api-pick, agent-tools). `install.sh --pack NAME[,NAME]|all`; one Claude plugin per pack.
- Always-loaded descriptions fall from about 1,900 to about 870 tokens. Opening a merged skill costs about 310 more tokens on average because of its table.
- The installer rewrites script paths in installed docs so commands run from the project root.
- `tools/check_layout.py`: every script in exactly one skill and mentioned, no dangling paths, no retired names, boot lists every skill.
- `evals/routing.py` with a frozen held-out set; guard tests so future description edits cannot lose a trigger.

## 0.5.0
- `ratchet`: iterate without breaking or drifting. Anchors the goal, scope and acceptance tests; records a floor of passing tests, public API and lint status; each `check` returns ACCEPT (floor rises, checkpoint saved), REJECT (regression, API change, out-of-scope file, edited pre-existing test, tampering, quality drop), STALL or DONE. Stops after three non-accepts. Checkpoints are git objects outside your branch and index; `revert` restores exactly.
- `loop.py mutate`: built-in mutation testing on changed Python functions, and Stryker, go-mutesting, cargo-mutants or PIT for other stacks. Reports each uncaught bug with file, line and the change made.
- `loop.py` lists one line per failure when more than three fail.
- `tamper.py`: catches deleted test files, commented-out assertions, added tolerances and broadened exceptions; judges weak assertions per test (a guard next to a strong check is fine); recognises moved test files. On the evaluation corpus: 19 of 19 cheats flagged, 0 of 12 honest changes failed.

## 0.4.0
- `prove-it` replaces `red-green`. Test-first loop built for agents: pick a mode (example, property, characterization or reproduction test), write types first, then a failing test, then the smallest change. Stop and report after three failed attempts at the same failure.
- `loop.py`: runs checks in tiers (fast: typecheck and lint; focused: tests related to changed files; full: whole suite) for Python, Node, Go, Rust and Java, and prints only the failing lines. Override in `.overmind/loop.json`.
- `tamper.py`: flags tests skipped, deleted, focused or weakened, swallowed errors, changed expected values and updated snapshots, against the merge-base with main.

## 0.3.0
- `log-fetch`: resolves a service to its runtime, cloud and log backend from IaC and queries it read-only, then summarises through `log-trace`. Backends: CloudWatch, Cloud Logging, Azure Monitor, Oracle, IBM, Alibaba SLS, DigitalOcean, Scaleway, OVH, Loki, Datadog, Splunk, Elastic/OpenSearch, New Relic, Honeycomb, OpenTelemetry. Never calls kubectl.
- Service map in `.overmind/services.json`, built once per repo. Detects log shippers (Fluent Bit, Fluentd, Vector, Promtail, Alloy, CloudWatch agent) and reads their output config; shipper evidence beats every other signal. Serverless stays on its cloud's native backend; aggregators win for container workloads.
- `legal-traps`: skill and scanner for COPPA, health data, wiretap claims, remote fonts, CAN-SPAM, TCPA, drip pricing, auto-renewal consent and cancellation, DMCA, BIPA, account deletion and privacy-policy gaps.

## 0.2.0
- New SRE and infrastructure skills: `log-trace`, `iac-check`, `crd-check`, `drift`, `k8s-triage`, `deps-check`, `preflight`, `ship`, `observe`, `slo`, `firefight`.
- Scripts for log triage (error, in-repo source line, Lambda/ECS/EKS detection), IaC risk checks, CRD and API validation, desired-vs-live drift with a state log, and dependency scanning.
- `vibe-check` runs extra commands listed in `.overmind/checks`.
- `hunt` now starts with `log-trace`; `boot` routes all new skills and prefers scripts over reading raw files.

## 0.1.0
- First release: core workflow, regulated (`reg-*`) and data/API/agent starter skills, `vibe-check` gate, installer.
