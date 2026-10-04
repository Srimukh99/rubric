"""plan_check.py: a clean plan passes, every planted defect is caught for its own reason,
--red proves tests are red, and the clean plan really executes."""
import contextlib
import io
import json
import os
import shutil
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "design", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import plan_check as PC  # noqa: E402
import plan_eval as EV  # noqa: E402


class Parsing(unittest.TestCase):
    def test_signatures(self):
        self.assertEqual(PC.signatures("`backoff(attempt: int) -> float`"), [("backoff", ["attempt"], "backoff(attempt: int) -> float")])
        self.assertEqual(PC.signatures("`with_retry(call, attempts: int = 3, sleep=time.sleep)`")[0][1],
                         ["call", "attempts", "sleep"])
        self.assertEqual(PC.signatures("`Unavailable(Exception)`")[0][0], "Unavailable")
        self.assertEqual(PC.signatures("`f(xs: dict[str, int], k)`")[0][1], ["xs", "k"])   # comma inside brackets
        self.assertEqual(PC.signatures("`def send(self, msg)`")[0][1], ["msg"])
        self.assertEqual(PC.signatures("none"), [])

    def test_files(self):
        self.assertEqual(PC.files("create a.py; modify b.py:3-9; test t.py"),
                         [("create", "a.py", None), ("modify", "b.py", (3, 9)), ("test", "t.py", None)])


class AgainstTheFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = EV.fixture()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def check(self, plan, *extra):
        return EV.run_check(self.d, plan, *extra)

    def test_clean_plan_passes(self):
        rc, out = self.check(EV.PLAN)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 FAIL, 0 WARN, 3 task(s)", out)

    def test_every_defect_is_caught_for_its_own_reason(self):
        for name, want, mutate in EV.DEFECTS:
            plan = mutate(EV.PLAN)
            self.assertNotEqual(plan, EV.PLAN, "mutation did not apply: " + name)
            rc, out = self.check(plan)
            self.assertEqual(rc, 1, name)
            self.assertTrue(any(l.startswith("FAIL") and want in l for l in out.splitlines()), "%s:\n%s" % (name, out))

    def test_red_proves_the_clean_plan_and_catches_a_vacuous_test(self):
        rc, out = self.check(EV.PLAN, "--red")
        self.assertEqual(rc, 0, out)
        self.assertIn("tests proven red", out)
        for name, want, mutate in EV.RED_ONLY:
            plan = mutate(EV.PLAN)
            self.assertEqual(self.check(plan)[0], 0, "only --red should see this: " + name)
            rc, out = self.check(plan, "--red")
            self.assertEqual(rc, 1, out)
            self.assertIn(want, out)

    def test_red_is_skipped_while_the_plan_fails(self):
        rc, out = self.check(EV.PLAN.replace("Stack: Python 3, unittest.", "Stack: TBD."), "--red")
        self.assertIn("--red skipped: fix the FAILs first", out)

    def test_waves(self):
        rc, out = self.check(EV.PLAN, "--waves")
        self.assertIn("wave 1: Task 1", out)
        self.assertIn("wave 3: Task 3", out)        # 2 consumes 1, 3 consumes 2

    def test_json(self):
        rc, out = self.check(EV.PLAN, "--json")
        tasks = json.loads(out)
        self.assertEqual([t["num"] for t in tasks], [1, 2, 3])
        self.assertEqual(tasks[1]["consumes"], ["backoff(attempt: int) -> float"])

    def test_a_typo_of_a_repo_name_gets_a_suggestion(self):
        plan = EV.PLAN.replace("`post(url, body)`", "`posts(url, body)`")
        self.assertIn("did you mean post?", self.check(plan)[1])

    def test_the_clean_plan_executes_cold(self):
        d = EV.fixture()
        self.addCleanup(shutil.rmtree, d, True)
        results = EV.execute(d)
        self.assertEqual(len(results), 3)
        self.assertEqual([r for r in results if not r[2]], [])


class Warnings(unittest.TestCase):
    def test_transcript_and_missing_file_map(self):
        d = EV.fixture()
        self.addCleanup(shutil.rmtree, d, True)
        body = "\n".join("    x%d = %d" % (i, i) for i in range(30))
        plan = EV.PLAN.replace(
            "- [ ] Implement `backoff(attempt: int) -> float` in billing/retry.py: 0.2 * 2 ** (attempt - 1), capped at 5.0.\n",
            "- [ ] Implement `backoff(attempt: int) -> float` in billing/retry.py:\n```python\ndef backoff(attempt):\n" + body + "\n```\n")
        rc, out = EV.run_check(d, plan)
        self.assertIn("that is the code, not a plan", out)
        start, end = EV.PLAN.index("## File map"), EV.PLAN.index("## Task 1")
        rc, out = EV.run_check(d, EV.PLAN[:start] + EV.PLAN[end:])
        self.assertIn("no file map", out)


if __name__ == "__main__":
    unittest.main()
