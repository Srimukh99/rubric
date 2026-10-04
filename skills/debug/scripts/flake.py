#!/usr/bin/env python3
"""flake: make a flaky or order-dependent test a deterministic one.

  flake.py rate TEST [-n 20]          how often it fails alone, and with what message
  flake.py polluter TEST              the earlier test(s) that make TEST fail
  flake.py polluter --creates PATH    the test(s) that leave PATH behind
  flake.py sleeps [PATH ...]          fixed waits in tests: the usual timing flake

`polluter` replays the suite's own order and binary-searches it, so each
polluter costs about log2(n) runs instead of n, and a pair that only breaks the
victim together is still found. When a later test cleans up after an earlier
one, it falls back to delta debugging. Runners: pytest and unittest (auto), or
`--cmd 'npx jest {tests}'` for anything that runs ids in the order given and
exits non-zero on failure. Every run is a fresh process; `-j N` runs N at once
(rate's repeats, and N split points per search round) for suites whose runs
cannot collide. Output stays short:
the verdict, the evidence, and the command that reproduces it.

Stdlib only.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

RUN_TIMEOUT = 300

UNITTEST_HELPER = r'''
import json, os, sys, unittest
cfg = json.loads(sys.argv[1])
os.chdir(cfg["cwd"])
for p in reversed(cfg["path"]):
    sys.path.insert(0, p)

def flat(s):
    for t in s:
        if isinstance(t, unittest.TestSuite):
            yield from flat(t)
        else:
            yield t

if cfg["mode"] == "list":
    suite = unittest.TestLoader().discover(cfg["start"], top_level_dir=cfg["top"])
    json.dump([t.id() for t in flat(suite)], open(cfg["out"], "w"))
    sys.exit(0)

class R(unittest.TestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.o = {}
    def _last(self, err, test):
        lines = self._exc_info_to_string(err, test).strip().splitlines()
        return lines[-1][:200] if lines else ""
    def addSuccess(self, t): self.o.setdefault(t.id(), "pass")
    def addFailure(self, t, e): self.o[t.id()] = "fail: " + self._last(e, t)
    def addError(self, t, e): self.o[t.id()] = "fail: " + self._last(e, t)
    def addSkip(self, t, r): self.o[t.id()] = "skip"
    def addExpectedFailure(self, t, e): self.o[t.id()] = "pass"
    def addUnexpectedSuccess(self, t): self.o[t.id()] = "fail: unexpected success"

loader = unittest.TestLoader()
suite = unittest.TestSuite()
for name in cfg["ids"]:
    try:
        suite.addTests(loader.loadTestsFromName(name))
    except Exception as exc:
        pass
r = R()
suite.run(r)
json.dump(r.o, open(cfg["out"], "w"))
'''

PYTEST_PLUGIN = r'''
import json, os
_out = {}
def pytest_runtest_logreport(report):
    if report.when == "call" or report.outcome != "passed":
        if report.outcome == "passed":
            _out.setdefault(report.nodeid, "pass")
        elif report.outcome == "skipped":
            _out.setdefault(report.nodeid, "skip")
        else:
            crash = getattr(report.longrepr, "reprcrash", None)
            msg = (crash.message if crash is not None else "") or ""
            lines = msg.strip().splitlines() or (report.longreprtext or "").strip().splitlines()
            # The assertion's own words, not just where it was raised.
            _out[report.nodeid] = "fail: " + (" ".join(l.strip() for l in lines[:2])[:200] if lines else report.when)
def pytest_sessionfinish(session):
    with open(os.environ["FLAKE_OUT"], "w") as fh:
        json.dump(_out, fh)
'''

SLEEP_RX = re.compile(
    r"\btime\.sleep\(|\basyncio\.sleep\(|\bsetTimeout\(|\bThread\.sleep\(|\btime\.Sleep\(|"
    r"\bcy\.wait\(\s*\d|\bpage\.waitForTimeout\(|\bsleep\s+\d|\bawait\s+sleep\(|\bdelay\(\s*\d")
TEST_FILE_RX = re.compile(r"(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.(?:py|go)|[^/]*\.(?:test|spec)\.[jt]sx?|"
                          r"[^/]*Test\.(?:java|kt)|[^/]*_spec\.rb)$")


class Runner:
    """Runs an ordered list of test ids in one fresh process; returns {id: outcome}."""

    def __init__(self, repo, kind, cmd=None, start=None, reset=None, timeout=RUN_TIMEOUT):
        self.repo, self.kind, self.cmd, self.reset, self.timeout = repo, kind, cmd, reset, timeout
        self.start = start or ("tests" if os.path.isdir(os.path.join(repo, "tests")) else ".")
        self.runs = 0
        self.lock = threading.Lock()
        self.tmp = tempfile.mkdtemp(prefix="flake-")
        self.env = {**os.environ, "PYTHONBREAKPOINT": "0", "PYTHONDONTWRITEBYTECODE": "1"}

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pytest_cmd(self):
        probe = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
        return [sys.executable, "-m", "pytest"] if probe.returncode == 0 else (
            [shutil.which("pytest")] if shutil.which("pytest") else None)

    def list(self):
        if self.kind == "pytest":
            base = self.pytest_cmd()
            p = subprocess.run(base + ["--collect-only", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"],
                               cwd=self.repo, capture_output=True, text=True, env=self.env, timeout=self.timeout)
            return [l.strip() for l in p.stdout.splitlines() if "::" in l and not l.startswith(("=", " "))]
        if self.kind == "unittest":
            out = os.path.join(self.tmp, "list.json")
            start = os.path.abspath(os.path.join(self.repo, self.start))
            cfg = {"mode": "list", "cwd": self.repo, "path": [start, self.repo], "start": start,
                   "top": start, "out": out}
            subprocess.run([sys.executable, "-c", UNITTEST_HELPER, json.dumps(cfg)], cwd=self.repo,
                           capture_output=True, env=self.env, timeout=self.timeout)
            with open(out) as fh:
                return [i for i in json.load(fh) if not i.startswith("unittest.loader")]
        raise SystemExit("flake: with --cmd, pass the suite's order with --order FILE (one id per line)")

    def run(self, ids):
        """{id: 'pass' | 'skip' | 'fail: <last line>'} for one run of `ids`, in order."""
        with self.lock:
            self.runs += 1
            n = self.runs
        if self.reset:
            subprocess.run(self.reset, shell=True, cwd=self.repo, capture_output=True, env=self.env)
        out = os.path.join(self.tmp, "run%d.json" % n)     # one file per run: runs may be concurrent
        try:
            if self.kind == "unittest":
                start = os.path.abspath(os.path.join(self.repo, self.start))
                cfg = {"mode": "run", "cwd": self.repo, "path": [start, self.repo], "ids": ids, "out": out}
                subprocess.run([sys.executable, "-c", UNITTEST_HELPER, json.dumps(cfg)], cwd=self.repo,
                               capture_output=True, env=self.env, timeout=self.timeout)
            elif self.kind == "pytest":
                plugin = os.path.join(self.tmp, "flake_plugin.py")
                if not os.path.exists(plugin):
                    with open(plugin, "w") as fh:
                        fh.write(PYTEST_PLUGIN)
                env = {**self.env, "FLAKE_OUT": out,
                       "PYTHONPATH": self.tmp + os.pathsep + self.env.get("PYTHONPATH", "")}
                subprocess.run(self.pytest_cmd() + ["-q", "-p", "flake_plugin", "-p", "no:randomly",
                                                    "-p", "no:cacheprovider", *ids],
                               cwd=self.repo, capture_output=True, env=env, timeout=self.timeout)
            else:
                p = subprocess.run(self.cmd.replace("{tests}", " ".join(shlex.quote(i) for i in ids)),
                                   shell=True, cwd=self.repo, capture_output=True, text=True, errors="replace",
                                   env=self.env, timeout=self.timeout)
                tail = (p.stdout + p.stderr).strip().splitlines()
                verdict = "pass" if p.returncode == 0 else "fail: " + (tail[-1][:200] if tail else "exit %d" % p.returncode)
                return {i: verdict for i in ids}
        except subprocess.TimeoutExpired:
            return {i: "fail: timed out after %ds" % self.timeout for i in ids}
        if not os.path.exists(out):
            return {}
        with open(out) as fh:
            return json.load(fh)


def detect(repo):
    if any(os.path.exists(os.path.join(repo, f)) for f in ("pytest.ini", "conftest.py", "tests/conftest.py")):
        return "pytest"
    py = os.path.join(repo, "pyproject.toml")
    if os.path.isfile(py) and "[tool.pytest" in open(py, encoding="utf-8", errors="replace").read():
        return "pytest"
    return "unittest"


def failed(outcome):
    return isinstance(outcome, str) and outcome.startswith("fail")


def ddmin(items, reproduces, budget):
    """Smallest subsequence of `items` (order kept) for which `reproduces` holds.

    Zeller's delta debugging: halves first, then complements, then finer cuts.
    One culprit costs about 2*log2(n) runs; a pair that only matters together
    is found too. Stops early when the run budget is spent.
    """
    cache = {}

    def test(sub):
        key = tuple(sub)
        if key not in cache:
            cache[key] = reproduces(sub)
        return cache[key]

    n = 2
    while len(items) >= 2 and budget():
        size = len(items)
        cuts = [c for c in (items[i * size // n:(i + 1) * size // n] for i in range(n)) if c]
        hit = next((c for c in cuts if budget() and test(c)), None)
        if hit is not None:
            items, n = hit, 2
            continue
        if n > 2:   # at n == 2 each complement is the other half, already tried
            rests = ([x for j, c in enumerate(cuts) if j != i for x in c] for i in range(len(cuts)))
            hit = next((r for r in rests if budget() and test(r)), None)
            if hit is not None:
                items, n = hit, max(n - 1, 2)
                continue
        if n >= size:
            break
        n = min(size, n * 2)
    return items


def culprits(items, reproduces, budget, jobs=1):
    """The tests that must run for `reproduces` to hold, one binary search each.

    Assumes more earlier tests never cure the failure - true of leaked state,
    a leftover file, a polluted cache. Each culprit then costs about log2(n)
    runs: k culprits in n tests take k*(log2 n + 1), where delta debugging
    pays several times that once k > 1. Returns None when the assumption
    breaks (a later test cleans up), so the caller can fall back to ddmin.
    """
    cache = {}
    order = {x: i for i, x in enumerate(items)}

    def key(sub):
        return tuple(sorted(sub, key=order.get))

    def test(sub):
        k = key(sub)
        if k not in cache:
            cache[k] = reproduces(list(k))
        return cache[k]

    pool_exec = ThreadPoolExecutor(jobs) if jobs > 1 else None

    def test_many(subs):
        """Run several subsets at once; returns their results in order."""
        todo = [s for s in subs if key(s) not in cache]
        if pool_exec and len(todo) > 1:
            for s, ok in zip(todo, pool_exec.map(lambda s: reproduces(list(key(s))), todo)):
                cache[key(s)] = ok
        return [test(s) for s in subs]

    found, pool = [], list(items)
    while budget():
        if found and test(found):
            return sorted(found, key=order.get)
        lo, hi = 1, len(pool)          # invariant: found + pool[:hi] reproduces
        if not pool:
            return None
        while lo < hi and budget():
            # jobs split points per round: log_(jobs+1) rounds instead of log2.
            k = min(jobs, hi - lo)
            mids = sorted({lo + (hi - lo) * (i + 1) // (k + 1) for i in range(k)} or {(lo + hi) // 2})
            results = test_many([found + pool[:m] for m in mids])
            first = next((m for m, ok in zip(mids, results) if ok), None)
            below = max([m for m, ok in zip(mids, results) if not ok], default=lo - 1)
            hi = first if first is not None else hi
            lo = below + 1
        if lo < hi:
            return None                # out of budget mid-search
        found.append(pool[hi - 1])
        pool = pool[:hi - 1]
    return None


def memo(fn):
    """One run per distinct ordered subset, however many layers ask."""
    seen = {}

    def wrapped(sub):
        key = tuple(sub)
        if key not in seen:
            seen[key] = fn(list(sub))
        return seen[key]
    return wrapped


def smallest(items, reproduces, budget, jobs=1):
    """culprits() when leaked state behaves, ddmin() when it does not."""
    reproduces = memo(reproduces)
    got = culprits(items, reproduces, budget, jobs)
    # Shrink whatever it found: free for one culprit, a couple of runs for a
    # pair, and the cure when a cleaner test broke the binary search.
    if got is not None and reproduces(got):
        return ddmin(got, reproduces, budget)
    return ddmin(items, reproduces, budget)


def remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.remove(path)


def runner_from(a):
    repo = os.path.abspath(a.repo)
    kind = "cmd" if a.cmd else (a.runner if a.runner != "auto" else detect(repo))
    return Runner(repo, kind, a.cmd, a.start, a.reset, a.timeout)


def show_cmd(r, ids):
    if r.kind == "pytest":
        return "pytest -p no:randomly " + " ".join(shlex.quote(i) for i in ids)
    if r.kind == "unittest":
        return "python3 -m unittest " + " ".join(ids) + ("" if r.start == "." else "   # from %s/" % r.start)
    return r.cmd.replace("{tests}", " ".join(shlex.quote(i) for i in ids))


def cmd_rate(a):
    r = runner_from(a)
    try:
        outcomes, times = [], []

        def once(_):
            t0 = time.time()
            o = r.run([a.test]).get(a.test, "fail: did not run (check the test id)")
            return o, time.time() - t0

        if a.jobs > 1 and not a.until_fail:
            with ThreadPoolExecutor(a.jobs) as ex:
                for o, dt in ex.map(once, range(a.n)):
                    outcomes.append(o)
                    times.append(dt)
        else:
            for i in range(a.n):
                o, dt = once(i)
                outcomes.append(o)
                times.append(dt)
                if a.until_fail and failed(o):
                    break
        fails = [o for o in outcomes if failed(o)]
        if fails and all(o == "fail: did not run (check the test id)" for o in fails):
            print("flake rate: %s did not run - check the id (list them: flake.py list)" % a.test)
            return 2
        print("flake rate: %s failed %d of %d runs alone (%d%%)"
              % (a.test, len(fails), len(outcomes), round(100 * len(fails) / len(outcomes))))
        kinds = {}
        for o in fails:
            kinds[o] = kinds.get(o, 0) + 1
        for o, k in sorted(kinds.items(), key=lambda kv: -kv[1])[:5]:
            print("  %3dx %s" % (k, o[6:]))
        ts = sorted(times)
        print("  run time: min %.2fs, median %.2fs, max %.2fs" % (ts[0], ts[len(ts) // 2], ts[-1]))
        if not fails:
            print("  never failed alone: if it fails in the suite, run `flake.py polluter %s`" % a.test)
        elif len(fails) == len(outcomes):
            print("  fails every time: not flaky, a plain bug - back to hunt.md step 1")
        else:
            print("  intermittent: look for time, randomness, ordering of sets/dicts, network or "
                  "shared files (`flake.py sleeps`)")
        return 1 if fails else 0
    finally:
        r.close()


def cmd_polluter(a):
    r = runner_from(a)
    budget = lambda: r.runs < a.max_runs
    try:
        order = [l.strip() for l in open(a.order) if l.strip()] if a.order else r.list()
        if a.creates:
            target = os.path.join(r.repo, a.creates)
            if os.path.lexists(target):
                print("flake polluter: %s already exists; remove it first so a run can be blamed" % a.creates)
                return 2

            def leaves(sub):
                r.run(sub)
                hit = os.path.lexists(target)
                remove(target)
                return hit

            if not leaves(order):
                print("flake polluter: the full suite (%d tests, %d runs) does not leave %s behind"
                      % (len(order), r.runs, a.creates))
                return 0
            found = smallest(order, leaves, budget)   # one shared path: never concurrent
            exact = len(found) <= 2
            print("flake polluter: %s is left behind by %s  (%d tests, %d runs)"
                  % (a.creates, " + ".join(found) if exact else "%d candidate tests" % len(found),
                     len(order), r.runs))
            print("  reproduce: %s; ls %s" % (show_cmd(r, found), a.creates))
            return 1

        if a.test not in order:
            close = [i for i in order if a.test.split("::")[-1].split(".")[-1] in i][:3]
            print("flake polluter: %s is not in the suite's order%s" % (a.test, (": did you mean " + ", ".join(close)) if close else ""))
            return 2
        before = order[:order.index(a.test)]
        alone = r.run([a.test]).get(a.test)
        if alone is None:
            print("flake polluter: %s did not run alone - check the id" % a.test)
            return 2
        if failed(alone):
            print("flake polluter: %s fails alone (%s), %d runs: not order-dependent. Try `flake.py rate %s`"
                  % (a.test, alone[6:], r.runs, a.test))
            return 1
        full = r.run(before + [a.test]).get(a.test)
        if not failed(full):
            print("flake polluter: %s passes after all %d earlier tests in suite order, %d runs: not reproduced. "
                  "If it fails only in CI, compare order, parallelism and environment; or `flake.py rate`"
                  % (a.test, len(before), r.runs))
            return 0
        seen = {}

        def victim_fails(sub):
            seen[tuple(sub)] = r.run(sub + [a.test]).get(a.test)
            return failed(seen[tuple(sub)])

        found = smallest(before, victim_fails, budget, a.jobs)
        confirm = seen.get(tuple(found)) or r.run(found + [a.test]).get(a.test)
        if not failed(confirm):
            print("flake polluter: no stable culprit within %d runs - the failure itself may be flaky; "
                  "`flake.py rate %s`" % (r.runs, a.test))
            return 1
        label = "polluter" if len(found) == 1 else "polluters, only together" if len(found) <= 4 else "candidates"
        print("flake polluter: %s fails after %s  [%s]" % (a.test, " + ".join(found[:4]) + (" ..." if len(found) > 4 else ""), label))
        print("  %d earlier tests, %d runs (a one-by-one scan needs up to %d)" % (len(before), r.runs, len(before) + 1))
        print("  failure: %s" % confirm[6:])
        print("  reproduce: %s" % show_cmd(r, found + [a.test]))
        print("  next: find the state %s leaves behind (globals, env, files, singletons, caches) and make it clean up, "
              "or make %s set up what it needs" % (found[0], a.test))
        return 1
    finally:
        r.close()


def cmd_sleeps(a):
    roots = a.paths or [p for p in ("tests", "test", "spec", "__tests__", "src") if os.path.isdir(os.path.join(a.repo, p))] or ["."]
    hits = []
    for root in roots:
        for d, dirs, files in os.walk(os.path.join(a.repo, root)):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__", ".venv", "vendor")]
            for f in files:
                path = os.path.join(d, f)
                rel = os.path.relpath(path, a.repo)
                if not TEST_FILE_RX.search(rel.replace(os.sep, "/")):
                    continue
                try:
                    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
                except OSError:
                    continue
                for i, line in enumerate(lines, 1):
                    if SLEEP_RX.search(line) and "flake: ok" not in line:
                        hits.append("%s:%d  %s" % (rel, i, line.strip()[:90]))
    print("flake sleeps: %d fixed wait(s) in test files" % len(hits))
    for h in hits[:20]:
        print("  " + h)
    if len(hits) > 20:
        print("  ... %d more" % (len(hits) - 20))
    if hits:
        print("  a fixed wait guesses how long something takes: poll for the condition itself, with a deadline. "
              "Mark a wait that is the behaviour under test with `flake: ok`.")
    return 1 if hits else 0


def cmd_list(a):
    r = runner_from(a)
    try:
        ids = r.list()
        print("flake list: %d tests (%s)" % (len(ids), r.kind))
        for i in ids[:a.limit]:
            print("  " + i)
        if len(ids) > a.limit:
            print("  ... %d more" % (len(ids) - a.limit))
        return 0
    finally:
        r.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="flake", description="make a flaky or order-dependent test deterministic")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".")
    common.add_argument("--runner", choices=("auto", "pytest", "unittest"), default="auto")
    common.add_argument("--start", help="unittest discovery dir (default: tests/ when present)")
    common.add_argument("--cmd", help="any runner: a command with {tests}, run in the order given")
    common.add_argument("--reset", help="shell command run before every run, to clear state between runs")
    common.add_argument("--timeout", type=int, default=RUN_TIMEOUT, help="seconds per run")
    common.add_argument("-j", "--jobs", type=int, default=1,
                        help="runs at once (default 1). Faster, but only for suites whose runs cannot collide "
                             "on shared files, ports or databases")
    sub = ap.add_subparsers(dest="what", required=True)
    p = sub.add_parser("rate", parents=[common], help="how often a test fails alone")
    p.add_argument("test")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--until-fail", action="store_true")
    p = sub.add_parser("polluter", parents=[common], help="the earlier test(s) that break TEST, or leave PATH")
    p.add_argument("test", nargs="?")
    p.add_argument("--creates", help="find the test(s) that leave this path behind")
    p.add_argument("--order", help="file with the suite's test ids, one per line, in run order")
    p.add_argument("--max-runs", type=int, default=60)
    p = sub.add_parser("sleeps", help="fixed waits in test files")
    p.add_argument("paths", nargs="*")
    p.add_argument("--repo", default=".")
    p = sub.add_parser("list", parents=[common], help="the suite's test ids, in run order")
    p.add_argument("--limit", type=int, default=50)
    a = ap.parse_args(argv)
    if a.what == "polluter" and not (a.test or a.creates):
        ap.error("polluter needs TEST or --creates PATH")
    return {"rate": cmd_rate, "polluter": cmd_polluter, "sleeps": cmd_sleeps, "list": cmd_list}[a.what](a)


if __name__ == "__main__":
    sys.exit(main())
