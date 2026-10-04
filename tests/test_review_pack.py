"""review_pack.py: a clean implementation of a plan gives no findings, each planted defect is named,
and the range guards refuse a review of the wrong thing."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "evals"))
sys.path.insert(0, os.path.join(ROOT, "skills", "review", "scripts"))
import review_eval as RE  # noqa: E402
import review_pack as RP  # noqa: E402


class AgainstTheFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d, cls.base, cls.clean = RE.implemented()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def setUp(self):
        RE.sh(self.d, "reset", "-q", "--hard", self.clean)

    def test_clean_implementation_has_no_findings(self):
        rc, out, package = RE.pack(self.d, self.base)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 FAIL, 0 WARN", out)
        self.assertIn("## Diff", package)
        self.assertIn("Task 2: Retry loop", package)

    def test_every_defect_is_named(self):
        for name, want, apply in RE.DEFECTS:
            RE.sh(self.d, "reset", "-q", "--hard", self.clean)
            apply(self.d)
            RE.sh(self.d, "add", "-A")
            RE.sh(self.d, *RE.ID, "commit", "-qm", name)
            rc, out, package = RE.pack(self.d, self.base)
            lines = [l for l in package.splitlines() if l.startswith("- **")]
            self.assertTrue(any(want in l for l in lines), "%s:\n%s" % (name, "\n".join(lines)))

    def test_reformatting_a_planned_test_is_not_a_change(self):
        """The contract is what the test checks, not how it is laid out."""
        RE.edit("tests/test_retry.py", "self.assertEqual([backoff(n) for n in (1, 2, 3, 9)], [0.2, 0.4, 0.8, 5.0])",
                "self.assertEqual(\n            [backoff(n) for n in (1, 2, 3, 9)],\n            [0.2, 0.4, 0.8, 5.0],\n        )")(self.d)
        RE.sh(self.d, "add", "-A")
        RE.sh(self.d, *RE.ID, "commit", "-qm", "reformat")
        rc, out, package = RE.pack(self.d, self.base)
        self.assertEqual(rc, 0, out)

    def test_task_scope(self):
        rc, out, package = RE.pack(self.d, self.base, "--task", "1")
        self.assertIn("planned for Task 3, outside this review's tasks", package)
        self.assertNotIn("Task 3: Client retries charges", package)

    def test_without_a_plan_the_gates_still_run(self):
        RE.edit("billing/client.py", "    return with_retry(", "    breakpoint()\n    return with_retry(")(self.d)
        RE.sh(self.d, "add", "-A")
        RE.sh(self.d, *RE.ID, "commit", "-qm", "debugger")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = RP.main(["--repo", self.d, "--base", self.base, "--out", os.path.join(self.d, ".rubric", "p.md")])
        self.assertEqual(rc, 1)
        self.assertIn("Debugger statement", out.getvalue())

    def test_range_guards(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(RP.main(["--repo", self.d, "--base", self.clean]), 2)
        self.assertIn("empty range", out.getvalue())
        side = RE.sh(self.d, "rev-parse", "HEAD")
        RE.sh(self.d, "checkout", "-q", "-b", "other", self.base)
        RE.sh(self.d, *RE.ID, "commit", "-q", "--allow-empty", "-m", "elsewhere")
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(RP.main(["--repo", self.d, "--base", side]), 2)
            self.assertIn("not an ancestor", out.getvalue())
        finally:
            RE.sh(self.d, "checkout", "-q", "-")


if __name__ == "__main__":
    unittest.main()
