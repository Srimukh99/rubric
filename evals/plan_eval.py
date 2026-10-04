#!/usr/bin/env python3
"""Plan check: does plan_check.py catch what would stop a cold agent?

A fixture repo (a small billing package), its design, and a clean three-task
plan in the blueprint format. Each case plants one defect a cold executor
would hit - a name that does not match between tasks, a file that is not
there, a test that already passes, a design line nobody covers - and asks
whether plan_check.py FAILs on it. Two controls must stay clean: the plan as
written, and `--red` on it (every test fails before its code exists).

Then the clean plan is executed the way a cold agent would: its tests are
written, a reference implementation of each task's signature is added, and
every `Expect PASS` command must pass. That is the evidence the format
carries enough to execute, not just to read.

The defects were written alongside the checker, so the catch rate is a floor
on what it covers, like every self-made eval here; read the cases.

Run: python3 evals/plan_eval.py [-v]
Stdlib only.
"""
import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "design", "scripts"))
import plan_check as PC  # noqa: E402

REPO = {
    "billing/__init__.py": "",
    "billing/http.py": "def post(url, body):\n    raise NotImplementedError('network call')\n",
    "billing/client.py": ("from billing.http import post\n\n\n"
                          "def charge(order):\n    return post('/charges', {'id': order})\n"),
    "tests/__init__.py": "",
    "docs/designs/2026-10-04-retry.md": """# Retry billing calls

Size: structural
Status: approved by Dana on 2026-10-04

## Problem
About 2% of calls to the billing API fail with a 503 and the user sees an error.

## Success
- The backoff between attempts is 0.2 s, doubled per attempt, capped at 5 s (`test_retry`).
- A charge that fails twice with a 503 succeeds on the third attempt (`test_retry`).

## Non-goals
- Retrying calls to any other vendor.

## Assumptions
None.

## Approaches considered
1. Retry in the client. Chosen.

## Data model
No change.

## Interfaces
`with_retry(call, attempts)` wraps any callable.

## Flow
```mermaid
sequenceDiagram
  client->>billing: charge
  billing-->>client: 503
  client->>billing: charge, attempt 2
```

## Failure modes
- Every attempt fails: the last error is raised, after 3 attempts (a test).
- A non-503 error: raised at once, never retried (a test).

## Testing
One test per failure mode, against a fake call.

## Rollout and undo
Behind a flag; undo by turning it off.

## Open questions
None.
""",
}

PLAN = """# Retry billing calls: plan

Design: docs/designs/2026-10-04-retry.md
Goal: Retry billing charges that fail with a 503, three attempts with backoff.
Approach: A small retry module wraps any call; the client wraps charge() in it.
Stack: Python 3, unittest.

## Constraints
- Three attempts at most; backoff 0.2 s doubled, capped at 5 s.

## File map
| File | Change | Responsibility |
| --- | --- | --- |
| billing/retry.py | create | the backoff schedule and the retry loop |
| billing/client.py | modify | wraps charge() in the retry loop |
| tests/test_retry.py | create | backoff and retry behaviour |
| tests/test_client.py | create | the client retries a 503 |

## Task 1: Backoff schedule
Covers: Success 1
Files: create billing/retry.py; create tests/test_retry.py
Mirrors: billing/http.py
Consumes: none
Produces: `backoff(attempt: int) -> float`

- [ ] Write the failing test in tests/test_retry.py:
```python
import unittest
from billing.retry import backoff


class Backoff(unittest.TestCase):
    def test_doubles_and_caps(self):
        self.assertEqual([backoff(n) for n in (1, 2, 3, 9)], [0.2, 0.4, 0.8, 5.0])
```
- [ ] Run `python3 -m unittest tests.test_retry -q`. Expect FAIL: `No module named 'billing.retry'`
- [ ] Implement `backoff(attempt: int) -> float` in billing/retry.py: 0.2 * 2 ** (attempt - 1), capped at 5.0.
- [ ] Run `python3 -m unittest tests.test_retry -q`. Expect PASS
- [ ] Commit: `git add billing/retry.py tests/test_retry.py && git commit -m "Add the backoff schedule"`

## Task 2: Retry loop
Covers: Success 2, Failure modes 1, Failure modes 2
Files: modify billing/retry.py; modify tests/test_retry.py
Consumes: `backoff(attempt: int) -> float`
Produces: `with_retry(call, attempts: int = 3, sleep=time.sleep)`; `Unavailable(Exception)`

- [ ] Write the failing test in tests/test_retry.py:
```python
from billing.retry import with_retry, Unavailable


class Retry(unittest.TestCase):
    def test_third_attempt_wins(self):
        results = [Unavailable(), Unavailable(), "ok"]
        def call():
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        self.assertEqual(with_retry(call, sleep=lambda s: None), "ok")

    def test_gives_up_after_three(self):
        def call():
            raise Unavailable()
        with self.assertRaises(Unavailable):
            with_retry(call, sleep=lambda s: None)

    def test_other_errors_are_not_retried(self):
        calls = []
        def call():
            calls.append(1)
            raise ValueError("bad order")
        with self.assertRaises(ValueError):
            with_retry(call, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)
```
- [ ] Run `python3 -m unittest tests.test_retry -q`. Expect FAIL: `cannot import name 'with_retry'`
- [ ] Implement `with_retry(call, attempts: int = 3, sleep=time.sleep)` in billing/retry.py: retry only `Unavailable`, sleeping backoff(n) between attempts.
- [ ] Run `python3 -m unittest tests.test_retry -q`. Expect PASS
- [ ] Commit: `git add billing/retry.py tests/test_retry.py && git commit -m "Retry 503s three times"`

## Task 3: Client retries charges
Covers: Success 2
Files: modify billing/client.py; create tests/test_client.py
Consumes: `with_retry(call, attempts: int = 3, sleep=time.sleep)`; `post(url, body)`
Produces: `charge(order, sleep=time.sleep)`

- [ ] Write the failing test in tests/test_client.py:
```python
import unittest
from unittest import mock
from billing import client
from billing.retry import Unavailable


class Client(unittest.TestCase):
    def test_charge_retries_a_503(self):
        with mock.patch.object(client, "post", side_effect=[Unavailable(), {"ok": True}]):
            self.assertEqual(client.charge("o-1", sleep=lambda s: None), {"ok": True})
```
- [ ] Run `python3 -m unittest tests.test_client -q`. Expect FAIL: `Unavailable`
- [ ] Implement `charge(order, sleep=time.sleep)` in billing/client.py: wrap the post in with_retry.
- [ ] Run `python3 -m unittest tests.test_client -q`. Expect PASS
- [ ] Commit: `git add billing/client.py tests/test_client.py && git commit -m "Retry billing charges"`
"""

# What a cold agent writes from each task's signature and one line.
REFERENCE = {
    "billing/retry.py": ("import time\n\n\nclass Unavailable(Exception):\n    pass\n\n\n"
                         "def backoff(attempt):\n    return min(0.2 * 2 ** (attempt - 1), 5.0)\n\n\n"
                         "def with_retry(call, attempts=3, sleep=time.sleep):\n"
                         "    for n in range(1, attempts + 1):\n        try:\n            return call()\n"
                         "        except Unavailable:\n            if n == attempts:\n                raise\n"
                         "            sleep(backoff(n))\n"),
    "billing/client.py": ("import time\n\nfrom billing.http import post\nfrom billing.retry import with_retry\n\n\n"
                          "def charge(order, sleep=time.sleep):\n"
                          "    return with_retry(lambda: post('/charges', {'id': order}), sleep=sleep)\n"),
}

T1_FAIL = "- [ ] Run `python3 -m unittest tests.test_retry -q`. Expect FAIL: `No module named 'billing.retry'`\n"
DEFECTS = [
    ("name differs between tasks", 'consumes with_retries, which no earlier task produces', lambda p: p.replace(
        "Consumes: `with_retry(call, attempts: int = 3, sleep=time.sleep)`; `post(url, body)`",
        "Consumes: `with_retries(call, attempts: int = 3, sleep=time.sleep)`; `post(url, body)`")),
    ("parameters differ between tasks", 'but Task 2 produces with_retry with', lambda p: p.replace(
        "Consumes: `with_retry(call, attempts: int = 3, sleep=time.sleep)`; `post(url, body)`",
        "Consumes: `with_retry(call)`; `post(url, body)`")),
    ("needs a later task", 'consumes charge, which Task 3 produces later', lambda p: p.replace("Consumes: `backoff(attempt: int) -> float`",
                                               "Consumes: `backoff(attempt: int) -> float`; `charge(order, sleep)`")),
    ("modifies a file that is not there", 'modifies billing/clients.py, which does not exist', lambda p: p.replace("Files: modify billing/client.py;",
                                                              "Files: modify billing/clients.py;")),
    ("creates a file that exists", 'creates billing/http.py, which already exists', lambda p: p.replace("Files: create billing/retry.py;",
                                                       "Files: create billing/http.py; create billing/retry.py;")),
    ("design line covered by no task", 'Failure modes 2 is covered by no task', lambda p: p.replace("Covers: Success 2, Failure modes 1, Failure modes 2",
                                                           "Covers: Success 2, Failure modes 1")),
    ("covers a design line that does not exist", 'covers Success 4, but the design has 2', lambda p: p.replace("Covers: Success 1\n", "Covers: Success 1, Success 4\n")),
    ("a step that decides nothing", "decides nothing: 'handle edge cases'", lambda p: p.replace(": wrap the post in with_retry.",
                                                        ": wrap the post in with_retry and handle edge cases.")),
    ("placeholder left in", "decides nothing: 'TBD'", lambda p: p.replace("Stack: Python 3, unittest.", "Stack: Python 3, TBD.")),
    ("test code does not parse", 'test code does not parse', lambda p: p.replace("    def test_doubles_and_caps(self):",
                                                     "    def test_doubles_and_caps(self)")),
    ("test imports a name no task produces", 'test imports jitter', lambda p: p.replace("from billing.retry import with_retry, Unavailable",
                                                                 "from billing.retry import with_retry, Unavailable, jitter")),
    ("test step with no test code", 'test step with no test code', lambda p: p[:p.index("```python", p.index("tests/test_client.py:"))]
        + p[p.index("```", p.index("```python", p.index("tests/test_client.py:")) + 9) + 4:]),
    ("no failing run before the code", 'missing a run that fails first', lambda p: p.replace(T1_FAIL, "")),
    ("failing run after the code", 'the failing run comes after the implementation', lambda p: p.replace(
        T1_FAIL + "- [ ] Implement `backoff(attempt: int) -> float` in billing/retry.py: 0.2 * 2 ** (attempt - 1), capped at 5.0.\n",
        "- [ ] Implement `backoff(attempt: int) -> float` in billing/retry.py: 0.2 * 2 ** (attempt - 1), capped at 5.0.\n" + T1_FAIL)),
    ("mirrors a file that is not there", 'mirrors billing/net.py, which does not exist', lambda p: p.replace("Mirrors: billing/http.py", "Mirrors: billing/net.py")),
    ("line range past the end of the file", 'is past its end', lambda p: p.replace("Files: modify billing/client.py;",
                                                                "Files: modify billing/client.py:40-60;")),
    ("[parallel] tasks share a file", 'are [parallel] but both touch billing/retry.py', lambda p: p.replace("## Task 2: Retry loop", "## Task 2: Retry loop [parallel]")
        .replace("## Task 3: Client retries charges", "## Task 3: Client retries charges [parallel]")
        .replace("Files: modify billing/client.py; create tests/test_client.py",
                 "Files: modify billing/client.py; modify billing/retry.py; create tests/test_client.py")),
    ("missing Produces line", "no 'Produces:' line", lambda p: p.replace("Produces: `charge(order, sleep=time.sleep)`\n", "")),
]
RED_ONLY = [
    ("a test that already passes", 'the test passes before its code exists', lambda p: p.replace(
        "        self.assertEqual([backoff(n) for n in (1, 2, 3, 9)], [0.2, 0.4, 0.8, 5.0])",
        "        self.assertTrue(True)").replace("from billing.retry import backoff\n", "")),
]


def fixture():
    d = tempfile.mkdtemp(prefix="plan-eval-")
    for rel, text in REPO.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True)
        with open(os.path.join(d, rel), "w") as fh:
            fh.write(text)
    subprocess.run(["git", "init", "-q"], cwd=d)
    subprocess.run(["git", "add", "-A"], cwd=d)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "base"], cwd=d)
    return d


def run_check(d, plan, *extra):
    path = os.path.join(d, "docs", "plans", "plan.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(plan)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = PC.main([path, "--repo", d, *extra])
    return rc, out.getvalue()


def execute(d):
    """Follow the clean plan as a cold agent: tests, then the reference code, then every PASS run."""
    plan = PC.parse(PLAN)
    for t in plan["tasks"]:
        for s in t["steps"]:
            if PC.TEST_STEP.search(s["text"]) and s.get("code"):
                path = os.path.join(d, PC.TEST_STEP.search(s["text"]).group(1))
                mode = "a" if os.path.exists(path) else "w"
                with open(path, mode) as fh:
                    fh.write(("\n\n" if mode == "a" else "") + s["code"].rstrip() + "\n")
    for rel, text in REFERENCE.items():
        with open(os.path.join(d, rel), "w") as fh:
            fh.write(text)
    results = []
    for t in plan["tasks"]:
        for s in t["steps"]:
            m = PC.RUN_STEP.search(s["text"])
            if m and m.group(2).lower() == "pass":
                p = subprocess.run(m.group(1), shell=True, cwd=d, capture_output=True, text=True)
                results.append((t["num"], m.group(1), p.returncode == 0, (p.stdout + p.stderr).strip()[-120:]))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plan-eval")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    d = fixture()
    try:
        rows, caught = [], 0
        rc, out = run_check(d, PLAN)
        clean_ok = rc == 0
        rc_red, out_red = run_check(d, PLAN, "--red")
        red_ok = rc_red == 0 and "tests proven red" in out_red
        for name, want, mutate in DEFECTS:
            plan = mutate(PLAN)
            assert plan != PLAN, "mutation did not apply: " + name
            rc, out = run_check(d, plan)
            # Caught means the FAIL names this defect, not that something failed.
            hit = rc == 1 and any(l.startswith("FAIL") and want in l for l in out.splitlines())
            caught += hit
            first = next((l for l in out.splitlines() if l.startswith("FAIL") and want in l),
                         next((l for l in out.splitlines() if l.startswith("FAIL")), out.splitlines()[-1]))
            rows.append((name, hit, first))
        red_caught = 0
        for name, want, mutate in RED_ONLY:
            plan = mutate(PLAN)
            rc_plain, _ = run_check(d, plan)
            rc, out = run_check(d, plan, "--red")
            hit = rc == 1 and rc_plain == 0 and any(l.startswith("FAIL") and want in l for l in out.splitlines())
            red_caught += hit
            first = next((l for l in out.splitlines() if l.startswith("FAIL") and want in l),
                         next((l for l in out.splitlines() if l.startswith("FAIL")), out.splitlines()[-1]))
            rows.append((name + " (needs --red)", hit, first))
        ex = execute(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("controls")
    print("  clean plan passes plan_check:       %s" % ("yes" if clean_ok else "NO\n" + out))
    print("  every test is red before its code:  %s" % ("yes" if red_ok else "NO\n" + out_red))
    print("\ndefects a cold executor would hit (one planted per case)")
    for name, hit, first in rows:
        line = "  %-44s %s" % (name, "caught" if hit else "MISSED")
        if a.v or not hit:
            line += "\n      " + first.split("  ", 1)[-1][:110]
        print(line)
    print("  %-44s %d/%d" % ("caught", caught + red_caught, len(DEFECTS) + len(RED_ONLY)))
    print("\nthe clean plan, executed cold (tests, reference code, every PASS run)")
    for num, cmd, ok, tail in ex:
        print("  Task %d  %-44s %s" % (num, cmd, "passes" if ok else "FAILS: " + tail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
