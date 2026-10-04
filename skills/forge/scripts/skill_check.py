#!/usr/bin/env python3
"""skill-check: is this skill change an improvement, by measurement?

For each changed skill (or the ones named, or --all):

  description  "Use when", no first person, no agent-specific tool names; WARN
               over 40 words, and WARN on a sentence that says what the skill
               does rather than when to use it - agents can follow that
               summary instead of reading the skill. Recast it as a condition,
               then let the routing check below decide
  triggers     evals/skill_triggers.json holds, per skill, prompts that should
               reach it and prompts that should not. Each is routed: a "should"
               outside the top 3 FAILs (WARN outside the top 1), a "should
               not" that lands on it FAILs. A changed skill with no triggers
               FAILs: unproven triggering is the failure being guarded
  regression   every dev and legacy routing case that was right at the base and
               is wrong now FAILs, naming the case and where it went. The
               held-out set is never used here: it is run once, by hand
  budget       always-loaded tokens now against the base

Run from the rubric repo: python3 skills/forge/scripts/skill_check.py [SKILL ...] [--base REF] [--all]
Stdlib only.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import io

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals"))
try:
    import routing as R  # noqa: E402
except ImportError:
    raise SystemExit("skill-check: run it inside the rubric repo (it needs evals/routing.py)")

TRIGGERS = ROOT / "evals" / "skill_triggers.json"
TOOL_NAMES = re.compile(r"\b(?:Bash|Read|Edit|Write|Glob|Grep|Task|WebFetch|NotebookEdit) tool\b|\bTodoWrite\b|"
                        r"\bsubagent_type\b|\bmcp__\w+")
FIRST_PERSON = re.compile(r"\b(?:I|I'm|I'll|me|my)\b")
DOES = re.compile(r"^(?:[A-Z][a-z]+s)\b(?!\s+(?:when|if)\b)")      # "Fetches ...", "Runs ...": what it does


def skills(root):
    out = {}
    for md in sorted(list(root.glob("skills/*/SKILL.md")) + list(root.glob("packs/*/skills/*/SKILL.md"))):
        out[md.parent.name] = md
    return out


def description(md):
    m = re.search(r"^description:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def base_tree(base):
    """The skills and packs folders at `base`, unpacked to a temp dir."""
    d = pathlib.Path(tempfile.mkdtemp(prefix="skill-check-"))
    data = subprocess.run(["git", "archive", base, "skills", "packs"], cwd=ROOT, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(d)
    return d


def route(root, cases):
    """[(text, want, got_skill, got_part_or_None, ok)] for routing cases against the skills under `root`."""
    docs, parts = R.load_new(root)
    idx = R.Index(docs)
    out = []
    for text, o in cases:
        skill, part = R.MOVED.get(o, (o, None))
        got = idx.rank(text)[0]
        gp = parts[skill].rank(text)[0] if (got == skill and skill in parts and part) else None
        out.append((text, o, got, gp, got == skill and (not part or skill not in parts or gp == part)))
    return out


def tokens(root):
    return sum(len(description(md)) for name, md in skills(root).items() if "/packs/" not in str(md)) // 4


def changed(base):
    names = subprocess.run(["git", "diff", "--name-only", base, "--", "skills", "packs"], cwd=ROOT,
                           capture_output=True, text=True).stdout.splitlines()
    names += subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "skills", "packs"], cwd=ROOT,
                            capture_output=True, text=True).stdout.splitlines()
    found = set()
    for n in names:
        parts = n.split("/")
        if parts[0] == "skills" and len(parts) > 1:
            found.add(parts[1])
        elif parts[0] == "packs" and len(parts) > 3:
            found.add(parts[3])
    return found


def default_base():
    for ref in ("origin/main", "main"):
        p = subprocess.run(["git", "merge-base", "HEAD", ref], cwd=ROOT, capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
    return "HEAD"


def main(argv=None):
    ap = argparse.ArgumentParser(description="check a skill change by measurement")
    ap.add_argument("skills", nargs="*")
    ap.add_argument("--base", help="compare against this ref (default: merge-base with main)")
    ap.add_argument("--all", action="store_true", help="check every skill, not only changed ones")
    a = ap.parse_args(argv)
    base = a.base or default_base()
    now = skills(ROOT)
    targets = set(now) if a.all else set(a.skills) or changed(base)
    unknown = sorted(targets - set(now))
    findings = []

    def add(level, where, msg):
        findings.append((level, where, msg))

    for n in unknown:
        add("FAIL", n, "no such skill")
    triggers = json.loads(TRIGGERS.read_text()) if TRIGGERS.exists() else {}
    docs, _ = R.load_new(ROOT)
    idx = R.Index(docs)
    for n in sorted(targets & set(now)):
        d = description(now[n])
        if not d.startswith("Use when"):
            add("FAIL", n, "description must start with 'Use when'")
        if FIRST_PERSON.search(d):
            add("FAIL", n, "description is in the first person: it is read as a condition, not as a voice")
        words = len(d.split())
        if words > 40:
            add("WARN", n, "description is %d words; every word loads in every session (aim for 40)" % words)
        for s in re.split(r"(?<=\.)\s+", d)[1:]:
            if DOES.match(s):
                add("WARN", n, "'%s' says what the skill does, not when to use it - recast it as a condition, "
                               "and keep the change only if routing holds" % s[:60])
        body = "\n".join(p.read_text(encoding="utf-8") for p in [now[n]] + sorted(now[n].parent.glob("references/*.md")))
        m = TOOL_NAMES.search(body)
        if m:
            add("FAIL", n, "names an agent-specific tool (%s): say what to do, not which tool" % m.group(0))
        t = triggers.get(n)
        if not t:
            add("FAIL", n, "no triggers in evals/skill_triggers.json: add 3 prompts that should reach it "
                           "and 2 that should not")
            continue
        for q in t.get("should", []):
            order = idx.rank(q)
            if n not in order[:3]:
                add("FAIL", n, "should reach it, routes to %s: %s" % (order[0], q[:70]))
            elif order[0] != n:
                add("WARN", n, "should reach it, ranks #%d behind %s: %s" % (order.index(n) + 1, order[0], q[:60]))
        for q in t.get("should_not", []):
            if idx.rank(q)[0] == n:
                add("FAIL", n, "should not reach it, but does: %s" % q[:70])
        if len(t.get("should", [])) < 3 or len(t.get("should_not", [])) < 2:
            add("WARN", n, "fewer than 3 'should' or 2 'should_not' triggers")

    # Regression against the base, on the shared routing sets.
    old_root = base_tree(base)
    try:
        data = json.loads((ROOT / "evals" / "routing_cases.json").read_text())
        cases = [("dev", c) for c in data["dev"]] + [("legacy", c) for c in R.legacy_recall()]
        before = route(old_root, [c for _, c in cases])
        after = route(ROOT, [c for _, c in cases])
        fixed = 0
        for (setname, _), b, x in zip(cases, before, after):
            if b[4] and not x[4]:
                where = x[2] if x[2] != R.MOVED.get(x[1], (x[1],))[0] else "%s, part %s" % (x[2], x[3])
                add("FAIL", setname, "was right at the base, now goes to %s: %s" % (where, x[0][:70]))
            fixed += (not b[4]) and x[4]
        t_old, t_new = tokens(old_root), tokens(ROOT)
    finally:
        import shutil
        shutil.rmtree(old_root, ignore_errors=True)

    for level, where, msg in sorted(findings, key=lambda f: (f[0] != "FAIL", f[1])):
        print("%-4s %-12s %s" % (level, where, msg))
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = sum(1 for f in findings if f[0] == "WARN")
    print("skill-check: %d FAIL, %d WARN, %d skill(s); routing: %d case(s) newly right, %d newly wrong; "
          "always loaded %d -> %d tokens" % (fails, warns, len(targets), fixed,
                                             sum(1 for f in findings if f[1] in ("dev", "legacy")), t_old, t_new))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
