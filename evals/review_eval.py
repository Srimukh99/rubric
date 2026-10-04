#!/usr/bin/env python3
"""Review pack: what does a reviewer no longer have to find by reading?

The billing fixture from plan_eval.py: the plan is committed, then implemented
the way a cold agent would (its tests, a reference implementation). That clean
range must give zero findings. Then one implementation defect at a time is
planted on top - an interface renamed, a parameter added, a planned test
renamed, a file changed outside the plan, a planned file never touched, a
weakened or skipped test, a secret, a debugger - and review_pack.py must name
each one before any reviewer reads the diff.

A case counts only when a finding names that defect. The defects were written
with the tool, so this is a floor, like every self-made eval here.

Run: python3 evals/review_eval.py [-v]
Stdlib only.
"""
import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "review", "scripts"))
import plan_eval as EV  # noqa: E402
import review_pack as RP  # noqa: E402

ID = ["-c", "user.email=a@b", "-c", "user.name=a"]
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"


def sh(d, *args):
    return subprocess.run(["git", *args], cwd=d, capture_output=True, text=True, check=True).stdout.strip()


def implemented():
    """(repo, base, clean head): the plan committed, then carried out."""
    d = EV.fixture()
    with open(os.path.join(d, ".gitignore"), "w") as fh:
        fh.write("__pycache__/\n.rubric/\n")
    os.makedirs(os.path.join(d, "docs", "plans"))
    with open(os.path.join(d, "docs", "plans", "plan.md"), "w") as fh:
        fh.write(EV.PLAN)
    sh(d, "add", "-A")
    sh(d, *ID, "commit", "-qm", "plan")
    base = sh(d, "rev-parse", "HEAD")
    results = EV.execute(d)
    assert all(ok for _, _, ok, _ in results), results
    sh(d, "add", "-A")
    sh(d, *ID, "commit", "-qm", "implement the plan")
    return d, base, sh(d, "rev-parse", "HEAD")


def edit(rel, old, new):
    def apply(d):
        p = os.path.join(d, rel)
        text = open(p).read()
        assert old in text, (rel, old)
        open(p, "w").write(text.replace(old, new, 1))
    return apply


def restore(rel, base_text_from):
    def apply(d):
        open(os.path.join(d, rel), "w").write(base_text_from)
    return apply


DEFECTS = [
    ("interface renamed", "planned interface `with_retry", edit(
        "billing/retry.py", "def with_retry(", "def with_retries(")),
    ("a parameter added", "`backoff` takes 2 parameter(s)", edit(
        "billing/retry.py", "def backoff(attempt):", "def backoff(attempt, cap=5.0):")),
    ("planned test renamed", "plan's test `test_doubles_and_caps` is missing or renamed", edit(
        "tests/test_retry.py", "def test_doubles_and_caps(", "def test_doubles(")),
    ("file changed outside the plan", "`billing/http.py` changed, but not in the plan", edit(
        "billing/http.py", "raise NotImplementedError('network call')", "raise NotImplementedError('network call!')")),
    ("planned file never touched", "Task 3 plans to modify this file, and the range does not touch it",
     restore("billing/client.py", EV.REPO["billing/client.py"])),
    ("test weakened", "the plan's test `test_doubles_and_caps` was changed", edit(
        "tests/test_retry.py", "self.assertEqual([backoff(n) for n in (1, 2, 3, 9)], [0.2, 0.4, 0.8, 5.0])",
        "self.assertTrue(True)")),
    ("test skipped", "tamper: skip-added", edit(
        "tests/test_retry.py", "    def test_gives_up_after_three(self):",
        "    @unittest.skip('later')\n    def test_gives_up_after_three(self):")),
    ("secret committed", "vibe-check: AWS access key", edit(
        "billing/retry.py", "import time\n", "import time\nKEY = '%s'\n" % AWS)),
    ("debugger left in", "vibe-check: Debugger statement", edit(
        "billing/client.py", "    return with_retry(", "    breakpoint()\n    return with_retry(")),
]


def pack(d, base, *extra):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = RP.main(["--repo", d, "--base", base, "--plan", "docs/plans/plan.md",
                      "--out", os.path.join(d, ".rubric", "review.md"), *extra])
    return rc, out.getvalue(), open(os.path.join(d, ".rubric", "review.md")).read()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="review-eval")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    d, base, clean = implemented()
    try:
        rc, out, package = pack(d, base)
        clean_ok = rc == 0 and "0 FAIL, 0 WARN" in out
        rows, caught = [], 0
        for name, want, apply in DEFECTS:
            sh(d, "reset", "-q", "--hard", clean)
            apply(d)
            sh(d, "add", "-A")
            sh(d, *ID, "commit", "-qm", "defect: " + name)
            rc, out, package = pack(d, base)
            hit = any(want in line for line in package.splitlines() if line.startswith("- **"))
            caught += hit
            rows.append((name, hit, next((l for l in package.splitlines() if want in l), out.splitlines()[0])))
        sh(d, "reset", "-q", "--hard", clean)
        rc, out, package = pack(d, base, "--task", "1")
        scoped = "planned for Task 3, outside this review's tasks" in package
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("controls")
    print("  clean implementation: no findings        %s" % ("yes" if clean_ok else "NO"))
    print("  --task 1 flags Task 3's files as out of scope  %s" % ("yes" if scoped else "NO"))
    print("\nimplementation defects, settled before a reviewer reads the diff")
    for name, hit, line in rows:
        print("  %-32s %s" % (name, "caught" if hit else "MISSED") + ("\n      " + line[:110] if a.v or not hit else ""))
    print("  %-32s %d/%d" % ("caught", caught, len(DEFECTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
