#!/usr/bin/env python3
"""review-pack: one file a reviewer reads, with the mechanical findings on top.

A reviewer's attention is the scarce thing. Everything a script can settle is
settled before the reviewer starts, so the review goes to judgement:

  plan        with --plan: every planned file changed and nothing else; every
              `Produces` defined at HEAD with the planned parameters; every
              test the plan wrote still there under its name
  gates       vibe_check over the range (secrets, debug leftovers, conflict
              markers) and tamper (tests skipped, deleted or weakened)
  package     commits, stat, the tasks in scope with their contracts, and the
              diff with context, written to one file

  python3 review_pack.py [--base REF] [--head REF] [--plan PLAN] [--task N ...]

Prints a short summary and the path it wrote. Exit 1 when a mechanical
finding FAILs: fix those before spending a reviewer on the diff.
Stdlib only.
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SKILLS, "design", "scripts"))
import plan_check as PC  # noqa: E402

VIBE = os.path.join(SKILLS, "ship", "scripts", "vibe_check.py")
TAMPER = os.path.join(SKILLS, "build", "scripts", "tamper.py")
TEST_NAMES = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(|\b(?:it|test)\(\s*['\"]([^'\"]+)['\"]", re.M)


def git(root, *args, check=True):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, errors="replace")
    if check and p.returncode != 0:
        raise SystemExit("review-pack: git %s failed: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout


def default_base(root):
    for ref in ("origin/main", "main", "origin/master", "master"):
        p = subprocess.run(["git", "merge-base", "HEAD", ref], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return git(root, "rev-list", "--max-parents=0", "HEAD").split()[0]


def show(root, head, path):
    p = subprocess.run(["git", "show", "%s:%s" % (head, path)], cwd=root, capture_output=True, text=True,
                       errors="replace")
    return p.stdout if p.returncode == 0 else None


def body(code, name):
    """A Python test function's body, whitespace-normalised, or None."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.dump(ast.Module(body=node.body, type_ignores=[]))
    return None


def defined(root, head, paths, name):
    """(params or None, path) where `name` is defined at HEAD among `paths`, else False."""
    for path in (p for p in paths if p.endswith(PC.SOURCE_EXT)):
        text = show(root, head, path)
        if text is None:
            continue
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                    a = node.args
                    params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs if x.arg not in ("self", "cls")]
                    return params, path
                if isinstance(node, ast.ClassDef) and node.name == name:
                    return None, path
        elif re.search(PC.DEFINES.format(re.escape(name)), text):
            return None, path
    return False


def plan_findings(root, base, head, plan, tasks, changed):
    out = []
    scope = [t for t in plan["tasks"] if not tasks or t["num"] in tasks]
    planned = {}
    for t in plan["tasks"]:
        for kind, path, _ in PC.files(t["fields"].get("Files", "")):
            planned.setdefault(path, []).append(t["num"])
    plan_paths = set()
    for t in scope:
        for kind, path, _ in PC.files(t["fields"].get("Files", "")):
            plan_paths.add(path)
            if path not in changed:
                out.append(("FAIL", path, "Task %d plans to %s this file, and the range does not touch it" % (t["num"], kind)))
    in_scope_all = set(planned) if not tasks else plan_paths
    for path in sorted(changed):
        if path in in_scope_all or path.startswith((".rubric/", "docs/plans/")):
            continue
        owner = planned.get(path)
        why = ("planned for Task %s, outside this review's tasks" % ", ".join(map(str, owner))) if owner \
            else "not in the plan"
        out.append(("WARN", path, "changed, but %s: explain it or move it out" % why))
    search = sorted(set(changed) | plan_paths)
    for t in scope:
        for name, params, sig in PC.signatures(t["fields"].get("Produces", "")):
            hit = defined(root, head, search, name)
            if hit is False:
                out.append(("FAIL", "Task %d" % t["num"], "planned interface `%s` is not defined at HEAD" % sig))
            elif hit[0] is not None and params is not None and len(hit[0]) != len(params):
                out.append(("FAIL", hit[1], "Task %d: `%s` takes %d parameter(s) (%s); the plan says %d"
                            % (t["num"], name, len(hit[0]), ", ".join(hit[0]) or "none", len(params))))
        for s in t["steps"]:
            m = PC.TEST_STEP.search(s["text"])
            if not (m and s.get("code")):
                continue
            path = m.group(1)
            text = show(root, head, path) or ""
            for want in [a or b for a, b in TEST_NAMES.findall(s["code"])]:
                if want not in text:
                    out.append(("FAIL", path, "Task %d: the plan's test `%s` is missing or renamed" % (t["num"], want)))
                elif path.endswith(".py"):
                    # The plan's tests are the contract: changing one changes what "done" means.
                    planned, actual = body(s["code"], want), body(text, want)
                    if planned is not None and actual is not None and planned != actual:
                        out.append(("FAIL", path, "Task %d: the plan's test `%s` was changed - update the plan with "
                                                  "the reason, or restore the test" % (t["num"], want)))
    return out


def gate_findings(root, base, head):
    out = []
    p = subprocess.run([sys.executable, VIBE, "--repo", root, "--range", "%s..%s" % (base, head)],
                       capture_output=True, text=True, errors="replace")
    for line in p.stdout.splitlines():
        m = re.match(r"^(FAIL|WARN)\s+(\S+)\s+(.*)$", line)
        if m:
            out.append((m.group(1), m.group(2), "vibe-check: " + m.group(3).strip()))
    p = subprocess.run([sys.executable, TAMPER, "--repo", root, "--base", base, "--json"],
                       capture_output=True, text=True, errors="replace")
    try:
        hits = json.loads(p.stdout or "[]")
    except ValueError:
        hits = []
    for h in hits if isinstance(hits, list) else []:
        level = str(h.get("level") or h.get("severity") or "WARN").upper()
        level = "FAIL" if level.startswith("FAIL") else "WARN" if level.startswith("WARN") else "INFO"
        loc = "%s:%s" % (h.get("file", "?"), h.get("line", "")) if h.get("line") else h.get("file", "?")
        out.append((level, loc, "tamper: %s %s" % (h.get("rule", ""), h.get("detail") or h.get("message") or "")))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="a review package with the mechanical findings on top")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", help="start of the range (default: merge-base with main)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--plan", help="the plan this range implements")
    ap.add_argument("--task", type=int, action="append", default=[], help="review only these tasks (repeatable)")
    ap.add_argument("--out", help="where to write the package (default: .rubric/review/<base>..<head>.md)")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.repo)
    base = git(root, "rev-parse", a.base or default_base(root)).strip()
    head = git(root, "rev-parse", a.head).strip()
    if base == head:
        print("review-pack: empty range %s..%s - nothing to review" % (base[:7], head[:7]))
        return 2
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=root).returncode != 0:
        print("review-pack: %s is not an ancestor of %s - wrong base or wrong branch" % (base[:7], head[:7]))
        return 2
    changed = {l.split("\t")[-1] for l in git(root, "diff", "--name-status", "%s..%s" % (base, head)).splitlines()
               if l and not l.startswith("D")}
    findings = []
    plan = None
    if a.plan:
        with open(a.plan if os.path.isabs(a.plan) else os.path.join(root, a.plan), encoding="utf-8") as fh:
            plan = PC.parse(fh.read())
        findings += plan_findings(root, base, head, plan, set(a.task), changed)
    findings += gate_findings(root, base, head)
    findings.sort(key=lambda f: ({"FAIL": 0, "WARN": 1}.get(f[0], 2), f[1]))

    rng = "%s..%s" % (base[:7], head[:7])
    out = a.out or os.path.join(root, ".rubric", "review", rng + ".md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = sum(1 for f in findings if f[0] == "WARN")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# Review package %s\n\n" % rng)
        fh.write("Settled by script before review: %d FAIL, %d WARN. A FAIL is a fact, not an opinion; "
                 "the review is for what a script cannot judge.\n\n" % (fails, warns))
        if findings:
            fh.write("## Mechanical findings\n\n")
            for level, where, msg in findings:
                fh.write("- **%s** `%s` %s\n" % (level, where, msg))
            fh.write("\n")
        if plan:
            scope = [t for t in plan["tasks"] if not a.task or t["num"] in a.task]
            fh.write("## Tasks in scope\n\n")
            for t in scope:
                fh.write("- Task %d: %s. Covers: %s. Produces: %s\n" % (
                    t["num"], t["title"], t["fields"].get("Covers", "-"), t["fields"].get("Produces", "-")))
            fh.write("\n")
        fh.write("## Commits\n\n```text\n%s```\n\n" % git(root, "log", "--oneline", "%s..%s" % (base, head)))
        fh.write("## Stat\n\n```text\n%s```\n\n" % git(root, "diff", "--stat", "%s..%s" % (base, head)))
        fh.write("## Diff\n\n```diff\n%s```\n" % git(root, "diff", "-U10", "%s..%s" % (base, head)))
    print("review-pack %s: %d FAIL, %d WARN, %d file(s) changed -> %s" % (rng, fails, warns, len(changed),
                                                                       os.path.relpath(out, root)))
    for level, where, msg in findings[:12]:
        print("  %-4s %s  %s" % (level, where, msg))
    if len(findings) > 12:
        print("  ... %d more in the package" % (len(findings) - 12))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
