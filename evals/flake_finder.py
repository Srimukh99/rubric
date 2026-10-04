#!/usr/bin/env python3
"""Flake finder: does flake.py find the test that breaks another, and how
many runs does it spend compared with trying earlier tests one by one?

Each scenario builds a throwaway unittest suite with a known culprit planted
at a seeded position, then asks both strategies to name it:

  ddmin     flake.py polluter - delta debugging over the suite's own order
  one-by-one  run each earlier test with the victim (or alone, for files),
            in order, until the failure reproduces

Scenarios: one in-memory polluter; a pair that only breaks the victim
together; a test that leaves a file behind; plus controls where the right
answer is "nothing to find" - a victim that fails alone, and one that never
fails. A run is one fresh test process, the unit that costs wall time.

Each size runs every scenario over several seeds, so the culprit lands at
different positions and neither strategy is flattered by where it sits.

Run: python3 evals/flake_finder.py [--sizes 16,64,256] [--seeds 5] [-j 4]
Stdlib only.
"""
import argparse
import contextlib
import io
import os
import random
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills", "debug", "scripts"))
import flake as F  # noqa: E402

PER_MODULE = 8


def build(d, n, plant):
    """A suite of n tests in modules of PER_MODULE; `plant(i)` returns a test body or None."""
    os.makedirs(os.path.join(d, "tests"))
    with open(os.path.join(d, "tests", "state.py"), "w") as fh:
        fh.write("FLAGS = {}\n")
    ids = []
    for m in range(0, n, PER_MODULE):
        name = "test_m%03d" % (m // PER_MODULE)
        body = ["import os, unittest", "import state", "", "class T(unittest.TestCase):"]
        for i in range(m, min(m + PER_MODULE, n)):
            code = plant(i) or "self.assertTrue(True)"
            body += ["    def test_%04d(self):" % i] + ["        " + l for l in code.splitlines()] + [""]
            ids.append("%s.T.test_%04d" % (name, i))
        with open(os.path.join(d, "tests", name + ".py"), "w") as fh:
            fh.write("\n".join(body) + "\n")
    return ids


VICTIM = "self.assertFalse(state.FLAGS.get('a') and state.FLAGS.get('b', True), 'state left by an earlier test')"


def scenarios(n, rng):
    v = n - 1 - rng.randrange(max(1, n // 8))
    p = rng.randrange(0, v)
    q = rng.choice([i for i in range(v) if i != p])
    return [
        ("one polluter", v, {p: "state.FLAGS['a'] = 1", v: VICTIM}, [p]),
        ("a pair, only together", v,
         {p: "state.FLAGS['a'] = 1", q: "state.FLAGS['b'] = 1",
          v: "self.assertFalse(state.FLAGS.get('a') and state.FLAGS.get('b'), 'both flags set')"}, sorted([p, q])),
        ("leaves a file", None, {p: "open('leftover.lock', 'w').close()"}, [p]),
        ("control: fails alone", v, {v: "self.fail('broken on its own')"}, None),
        ("control: never fails", v, {v: VICTIM}, None),
    ]


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = fn(*args)
    return rc, out.getvalue()


JOBS = 1


def ddmin_answer(d, ids, victim, creates):
    argv = ["polluter", "--repo", d, "--max-runs", "200", "-j", str(JOBS)] + (["--creates", creates] if creates else [ids[victim]])
    t0 = time.time()
    rc, out = quiet(F.main, argv)
    secs = time.time() - t0
    m = __import__("re").search(r"(\d+) runs", out)
    runs = int(m.group(1)) if m else None
    named = sorted(int(i.rsplit("_", 1)[1]) for i in ids if i in out and (victim is None or i != ids[victim]))
    return named, runs, secs, out.strip().splitlines()[0]


def one_by_one(d, ids, victim, creates):
    """Try each earlier test with the victim, in order; stop at the first reproduction."""
    r = F.Runner(d, "unittest")
    t0 = time.time()
    try:
        if creates:
            target = os.path.join(d, creates)
            for i, t in enumerate(ids):
                r.run([t])
                if os.path.exists(target):
                    os.remove(target)
                    return [i], r.runs, time.time() - t0
            return [], r.runs, time.time() - t0
        if F.failed(r.run([ids[victim]]).get(ids[victim])):
            return [], r.runs, time.time() - t0
        for i in range(victim):
            if F.failed(r.run([ids[i], ids[victim]]).get(ids[victim])):
                return [i], r.runs, time.time() - t0
        return [], r.runs, time.time() - t0
    finally:
        r.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="flake-finder")
    ap.add_argument("--sizes", default="16,64,256")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("-v", action="store_true", help="one line per case")
    ap.add_argument("-j", "--jobs", type=int, default=1, help="pass -j to flake.py")
    ap.add_argument("--only", help="only scenarios whose name contains this")
    a = ap.parse_args(argv)
    global JOBS
    JOBS = a.jobs
    rows, totals = {}, {"flake.py": [0, 0, 0.0], "one-by-one": [0, 0, 0.0]}
    cases = 0
    for n in [int(x) for x in a.sizes.split(",")]:
        for seed in range(a.seeds):
            rng = random.Random(1000 * n + seed)
            for name, victim, plants, want in scenarios(n, rng):
                if a.only and a.only not in name:
                    continue
                d = tempfile.mkdtemp(prefix="flake-eval-")
                try:
                    ids = build(d, n, plants.get)
                    creates = "leftover.lock" if victim is None else None
                    got_d, runs_d, s_d, line = ddmin_answer(d, ids, victim, creates)
                    got_o, runs_o, s_o = one_by_one(d, ids, victim, creates)
                finally:
                    shutil.rmtree(d, ignore_errors=True)
                exp = want or []
                cases += 1
                row = rows.setdefault((name, n), {"flake.py": [0, 0, 0.0], "one-by-one": [0, 0, 0.0], "k": 0})
                row["k"] += 1
                for k, got, runs, secs in (("flake.py", got_d, runs_d or 0, s_d), ("one-by-one", got_o, runs_o, s_o)):
                    for acc in (row[k], totals[k]):
                        acc[0] += got == exp
                        acc[1] += runs
                        acc[2] += secs
                if a.v or got_d != exp:
                    print("  %-22s n=%-4d seed=%d flake.py: %s" % (name, n, seed, line))
    print("%-24s %5s | %-28s | %-28s" % ("scenario", "tests", "flake.py: right, mean runs", "one-by-one: right, mean runs"))
    print("-" * 92)
    for (name, n), row in rows.items():
        k = row["k"]
        cell = lambda acc: "%d/%d, %5.1f runs, %4.1fs" % (acc[0], k, acc[1] / k, acc[2] / k)
        print("%-24s %5d | %-28s | %-28s" % (name, n, cell(row["flake.py"]), cell(row["one-by-one"])))
    print("-" * 92)
    for k, (right, runs, secs) in totals.items():
        print("%-10s right %d/%d, %d runs, %.0fs" % (k, right, cases, runs, secs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
