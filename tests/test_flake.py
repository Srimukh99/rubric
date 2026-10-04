"""flake.py: the search finds the right tests in few runs, and the commands say the right thing."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "debug", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "evals"))
import flake as F  # noqa: E402
import flake_finder as E  # noqa: E402


class Search(unittest.TestCase):
    """Against synthetic oracles, where the right answer and the run count are exact."""

    def find(self, n, reproduces, how=F.smallest):
        calls = []
        got = how(list(range(n)), lambda s: (calls.append(1), reproduces(s))[1], lambda: len(calls) < 500)
        return got, len(calls)

    def test_one_culprit_in_log_runs(self):
        for n, c in ((16, 5), (256, 200), (1024, 3)):
            got, runs = self.find(n, lambda s: c in s)
            self.assertEqual(got, [c])
            self.assertLessEqual(runs, n.bit_length() + 2, n)

    def test_a_pair_only_together(self):
        got, runs = self.find(256, lambda s: 7 in s and 250 in s)
        self.assertEqual(got, [7, 250])
        self.assertLess(runs, 30)

    def test_beats_plain_ddmin_on_several_culprits(self):
        rep = lambda s: {7, 8, 250} <= set(s)
        self.assertEqual(self.find(256, rep)[0], [7, 8, 250])
        self.assertLess(self.find(256, rep)[1] * 2, self.find(256, rep, F.ddmin)[1])

    def test_a_cleaner_in_between_falls_back_and_stays_minimal(self):
        """A later test that cleans up breaks the binary search's assumption."""
        def rep(s):
            return 10 in s and not (30 in s and s.index(30) > s.index(10))
        self.assertEqual(self.find(64, rep)[0], [10])

    def test_parallel_search_finds_the_same_answers_in_fewer_rounds(self):
        import threading
        for n, cul in ((256, {200}), (256, {7, 250}), (1024, {3, 700}), (64, {0}), (64, {63})):
            calls, rounds, lock = [], [], threading.Lock()
            def rep(s):
                with lock:
                    calls.append(1)
                return cul <= set(s)
            seq = F.smallest(list(range(n)), rep, lambda: len(calls) < 500)
            seq_runs = len(calls)
            calls.clear()
            par = F.smallest(list(range(n)), rep, lambda: len(calls) < 500, jobs=4)
            self.assertEqual(par, seq, (n, cul))
            self.assertLess(len(calls), seq_runs * 3, (n, cul))   # parallel spends more runs, not wildly more

    def test_budget_is_respected(self):
        calls = []
        F.smallest(list(range(1024)), lambda s: (calls.append(1), {1, 900} <= set(s))[1], lambda: len(calls) < 5)
        self.assertLessEqual(len(calls), 6)


def suite(n, plants):
    d = tempfile.mkdtemp(prefix="flake-test-")
    ids = E.build(d, n, plants.get)
    return d, ids


def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = F.main(argv)
    return rc, out.getvalue()


class Commands(unittest.TestCase):
    """Real unittest suites in throwaway dirs: every run is a real process."""

    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def make(self, n, plants):
        d, ids = suite(n, plants)
        self.dirs.append(d)
        return d, ids

    def test_polluter_names_the_test_and_how_to_reproduce(self):
        d, ids = self.make(32, {9: "state.FLAGS['a'] = 1", 31: E.VICTIM})
        rc, out = run(["polluter", ids[31], "--repo", d])
        self.assertEqual(rc, 1)
        self.assertIn("fails after %s  [polluter]" % ids[9], out)
        self.assertIn("state left by an earlier test", out)          # the assertion's words
        self.assertIn("reproduce: python3 -m unittest %s %s" % (ids[9], ids[31]), out)

    def test_pair_is_reported_as_together(self):
        d, ids = self.make(32, {4: "state.FLAGS['a'] = 1", 20: "state.FLAGS['b'] = 1",
                                31: "self.assertFalse(state.FLAGS.get('a') and state.FLAGS.get('b'))"})
        rc, out = run(["polluter", ids[31], "--repo", d])
        self.assertIn("%s + %s  [polluters, only together]" % (ids[4], ids[20]), out)

    def test_fails_alone_is_not_order_dependent(self):
        d, ids = self.make(16, {15: "self.fail('broken')"})
        rc, out = run(["polluter", ids[15], "--repo", d])
        self.assertIn("fails alone", out)
        self.assertIn("1 runs", out)

    def test_never_fails_costs_two_runs(self):
        d, ids = self.make(64, {63: E.VICTIM})
        rc, out = run(["polluter", ids[63], "--repo", d])
        self.assertEqual(rc, 0)
        self.assertIn("not reproduced", out)
        self.assertIn("2 runs", out)

    def test_creates(self):
        d, ids = self.make(32, {21: "open('leftover.lock', 'w').close()"})
        rc, out = run(["polluter", "--creates", "leftover.lock", "--repo", d])
        self.assertIn("left behind by %s" % ids[21], out)
        self.assertFalse(os.path.exists(os.path.join(d, "leftover.lock")))   # cleaned between runs

    def test_creates_refuses_when_the_path_already_exists(self):
        d, ids = self.make(8, {})
        open(os.path.join(d, "leftover.lock"), "w").close()
        self.assertEqual(run(["polluter", "--creates", "leftover.lock", "--repo", d])[0], 2)

    def test_unknown_id_is_named(self):
        d, ids = self.make(8, {})
        rc, out = run(["polluter", "test_m000.T.test_9999", "--repo", d])
        self.assertEqual(rc, 2)
        self.assertIn("not in the suite's order", out)

    def test_rate_counts_failures_and_groups_messages(self):
        d, ids = self.make(8, {3: "import random\nself.assertGreater(random.random(), 0.5, 'lost the race')"})
        rc, out = run(["rate", ids[3], "-n", "30", "--repo", d])
        self.assertRegex(out, r"failed (\d+) of 30 runs alone")
        fails = int(out.split("failed ")[1].split(" ")[0])
        self.assertTrue(3 <= fails <= 27, out)          # p=0.5: outside this is ~1e-5
        self.assertIn("lost the race", out)
        self.assertIn("intermittent", out)

    def test_rate_on_a_steady_test(self):
        d, ids = self.make(8, {})
        rc, out = run(["rate", ids[2], "-n", "3", "--repo", d])
        self.assertEqual(rc, 0)
        self.assertIn("failed 0 of 3", out)

    def test_cmd_runner_with_an_order_file(self):
        """Any runner that takes ids in order and exits non-zero on failure."""
        d, ids = self.make(16, {5: "state.FLAGS['a'] = 1", 15: E.VICTIM})
        with open(os.path.join(d, "order.txt"), "w") as fh:
            fh.write("\n".join(ids))
        cmd = "cd tests && %s -m unittest {tests}" % sys.executable
        rc, out = run(["polluter", ids[15], "--repo", d, "--cmd", cmd, "--order", os.path.join(d, "order.txt")])
        self.assertIn("fails after %s" % ids[5], out)


class Sleeps(unittest.TestCase):
    def test_finds_fixed_waits_and_honours_the_marker(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "tests"))
        with open(os.path.join(d, "tests", "test_a.py"), "w") as fh:
            fh.write("import time\ntime.sleep(0.5)\ntime.sleep(1)  # flake: ok, debounce under test\n")
        with open(os.path.join(d, "tests", "helper.py"), "w") as fh:
            fh.write("import time\ntime.sleep(2)\n")              # not a test file
        with open(os.path.join(d, "tests", "a.test.js"), "w") as fh:
            fh.write("await new Promise(r => setTimeout(r, 50))\n")  # flake: ok - fixture text
        rc, out = run(["sleeps", "--repo", d])
        self.assertIn("2 fixed wait(s)", out)
        self.assertIn("tests/test_a.py:2", out)
        self.assertIn("tests/a.test.js:1", out)


@unittest.skipUnless(shutil.which("pytest") or subprocess.run([sys.executable, "-c", "import pytest"],
                                                              capture_output=True).returncode == 0, "needs pytest")
class Pytest(unittest.TestCase):
    def test_polluter_under_pytest(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        os.makedirs(os.path.join(d, "tests"))
        with open(os.path.join(d, "pytest.ini"), "w") as fh:
            fh.write("[pytest]\n")
        with open(os.path.join(d, "tests", "state.py"), "w") as fh:
            fh.write("CACHE = {}\n")
        with open(os.path.join(d, "tests", "test_x.py"), "w") as fh:
            fh.write("import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nimport state\n"
                     "def test_a():\n    state.CACHE['u'] = 1\n"
                     "def test_b():\n    assert True\n"
                     "def test_c():\n    assert state.CACHE.get('u') is None, 'cache leaked'\n")
        rc, out = run(["polluter", "tests/test_x.py::test_c", "--repo", d])
        self.assertIn("fails after tests/test_x.py::test_a", out)
        self.assertIn("cache leaked", out)


if __name__ == "__main__":
    unittest.main()
