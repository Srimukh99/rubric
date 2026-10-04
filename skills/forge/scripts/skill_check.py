#!/usr/bin/env python3
"""skill-check: lint a skill anywhere, scaffold one, and inside rubric guard the library.

  skill_check.py PATH [--triggers FILE] [--against DIR ...]
      Any skill folder, for any agent or project: name and folder, the
      description (a condition, not a summary), length, links to files that
      exist, scripts it names, placeholders left in. With --triggers, routes
      prompts that should and should not reach it against the other skills in
      the same folder (and any --against folders).

  skill_check.py new NAME --type discipline|technique|pattern|reference [--dir DIR]
      A skeleton for that type, with <slots> the check FAILs on until filled.

  skill_check.py [SKILL ...] [--all] [--base REF]
      Inside the rubric repo: every changed skill's triggers from
      evals/skill_triggers.json, every dev and legacy routing case a change
      breaks against the base, agent-specific tool names, and the always-loaded
      token change. The held-out set is never used here.

Stdlib only.
"""
import argparse
import io
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
IN_RUBRIC = (ROOT / "evals" / "routing.py").exists() and (ROOT / "skills" / "forge").exists()
if IN_RUBRIC:
    sys.path.insert(0, str(ROOT / "evals"))
    import routing as R  # noqa: E402

TRIGGERS = ROOT / "evals" / "skill_triggers.json"
TOOL_NAMES = re.compile(r"\b(?:Bash|Read|Edit|Write|Glob|Grep|Task|WebFetch|NotebookEdit) tool\b|\bTodoWrite\b|"
                        r"\bsubagent_type\b|\bmcp__\w+")
FIRST_PERSON = re.compile(r"\b(?:I|I'm|I'll|me|my)\b")
DOES = re.compile(r"^(?:[A-Z][a-z]+s)\b(?!\s+(?:when|if)\b)")      # "Fetches ...", "Runs ...": what it does
PLACEHOLDER = re.compile(r"<[a-z][a-z0-9 ,./'-]{2,60}>|\bTBD\b|\bTODO\b|\?\?\?")
NAME_RX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STOP = set("a an the to of and or for in on at by with from is are was be it this that these those as into when use "
           "you your we our i my me can do does should how what which who why not no so if then than there their".split())


# ---------- a small ranker, so trigger routing works outside the rubric repo ----------

def _stem(w):
    for suf in ("ings", "ing", "ied", "ies", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _toks(text):
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


class Ranker:
    """TF-IDF cosine over name + description: a transparent stand-in for an agent choosing a skill."""

    def __init__(self, docs):
        self.ids = list(docs)
        tfs = {i: self._tf(_toks(t)) for i, t in docs.items()}
        df = {}
        for tf in tfs.values():
            for w in tf:
                df[w] = df.get(w, 0) + 1
        n = len(docs)
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self.vec = {i: self._vec(tf) for i, tf in tfs.items()}

    @staticmethod
    def _tf(ts):
        tf = {}
        for w in ts:
            tf[w] = tf.get(w, 0) + 1
        return tf

    def _vec(self, tf):
        v = {w: (1 + math.log(c)) * self.idf.get(w, 1.0) for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / norm for w, x in v.items()}

    def rank(self, query):
        q = self._vec(self._tf(_toks(query)))
        scored = [(sum(q.get(w, 0) * x for w, x in self.vec[i].items()), i) for i in self.ids]
        return [i for s, i in sorted(scored, key=lambda t: (-t[0], t[1]))]


# ---------- any skill folder ----------

def frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, text[end + 4:]


def prose(text):
    """Text outside fenced and inline code: placeholders in examples are examples."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def lint_folder(folder, add):
    md = folder / "SKILL.md"
    if not md.exists():
        add("FAIL", folder.name, "no SKILL.md in %s" % folder)
        return None, None
    text = md.read_text(encoding="utf-8")
    meta, body = frontmatter(text)
    if meta is None:
        add("FAIL", "SKILL.md", "no frontmatter (--- name / description ---)")
        return None, None
    name, desc = meta.get("name", ""), meta.get("description", "")
    if not name:
        add("FAIL", "SKILL.md", "no name")
    elif not NAME_RX.match(name) or len(name) > 64:
        add("FAIL", "SKILL.md", "name '%s' must be lowercase letters, digits and hyphens, 64 characters at most" % name)
    elif name != folder.name:
        add("WARN", "SKILL.md", "name '%s' differs from its folder '%s'" % (name, folder.name))
    if not desc:
        add("FAIL", "SKILL.md", "no description: nothing tells an agent when to load it")
    else:
        if len(desc) > 1024:
            add("FAIL", "SKILL.md", "description is %d characters (most agents cap it at 1024)" % len(desc))
        if not (desc[0] in "\"'") and ": " in desc:
            add("FAIL", "SKILL.md", "description contains ': ' unquoted, which breaks the YAML; quote it or rephrase")
        if not desc.strip("\"'").startswith("Use when"):
            add("WARN", "SKILL.md", "description does not start with 'Use when': state the condition for loading it")
        if FIRST_PERSON.search(desc):
            add("WARN", "SKILL.md", "description is in the first person; write the condition, not a voice")
        if len(desc.split()) > 40:
            add("WARN", "SKILL.md", "description is %d words; it loads in every session (aim for 40)" % len(desc.split()))
        for s in re.split(r"(?<=\.)\s+", desc.strip("\"'"))[1:]:
            if DOES.match(s):
                add("WARN", "SKILL.md", "'%s' says what the skill does, not when to use it; an agent can act on "
                                        "this and skip the skill - recast it as a condition" % s[:50])
    lines = body.count("\n")
    if lines > 500:
        add("FAIL", "SKILL.md", "body is %d lines; move detail into references/ files read on demand" % lines)
    elif lines > 200:
        add("WARN", "SKILL.md", "body is %d lines; the always-read part should be short (aim under 150)" % lines)
    files = [md] + sorted(folder.rglob("*.md"))
    files = list(dict.fromkeys(f for f in files if f.is_file()))
    alltext = {f: f.read_text(encoding="utf-8", errors="replace") for f in files}
    linked = set()
    for f, t in alltext.items():
        for m in re.finditer(r"(?:\]\(|`)((?:references|scripts|assets)/[\w./-]+)", t):
            target = m.group(1).rstrip(".`)")
            linked.add(target)
            if not (folder / target).exists():
                add("FAIL", f.relative_to(folder).as_posix(), "points at %s, which does not exist" % target)
        for m in PLACEHOLDER.finditer(prose(t)):
            add("FAIL", f.relative_to(folder).as_posix(), "placeholder left in: %s" % m.group(0))
    for ref in sorted((folder / "references").glob("*.md")) if (folder / "references").is_dir() else []:
        rel = ref.relative_to(folder).as_posix()
        if rel not in linked:
            add("WARN", rel, "is never pointed at, so an agent will not find it")
    for script in sorted((folder / "scripts").iterdir()) if (folder / "scripts").is_dir() else []:
        if script.is_file() and script.name not in "\n".join(alltext.values()):
            add("WARN", "scripts/" + script.name, "is never named in the skill's text, so an agent will not run it")
    if not any(re.search(r"^#+\s*Done when", t, re.M) for t in alltext.values()):
        add("WARN", "SKILL.md", "no 'Done when': say what observable state means the job is finished")
    return name or folder.name, desc


def skill_docs(dirs):
    """{name: 'name words + description'} for every skill under the given folders."""
    docs = {}
    for d in dirs:
        for md in sorted(pathlib.Path(d).glob("*/SKILL.md")):
            meta, _ = frontmatter(md.read_text(encoding="utf-8"))
            if meta and meta.get("description"):
                n = meta.get("name") or md.parent.name
                docs[n] = n.replace("-", " ") + " " + meta["description"]
    return docs


def route_triggers(name, triggers, docs, add):
    if len(docs) < 2:
        add("WARN", "triggers", "no other skills beside it to compete with; pass --against DIR to route for real")
        return
    rank = Ranker(docs).rank
    for q in triggers.get("should", []):
        order = rank(q)
        # Among a project's handful of skills the agent loads one: second place is a miss.
        if order[0] != name:
            add("FAIL", "triggers", "should reach it, routes to %s (it ranks #%d): %s"
                % (order[0], order.index(name) + 1, q[:70]))
    for q in triggers.get("should_not", []):
        if rank(q)[0] == name:
            add("FAIL", "triggers", "should not reach it, but does: %s" % q[:70])
    if len(triggers.get("should", [])) < 3 or len(triggers.get("should_not", [])) < 2:
        add("WARN", "triggers", "fewer than 3 'should' or 2 'should_not' prompts")


def check_path(a):
    target = pathlib.Path(a.target).resolve()
    folder = target.parent if target.name == "SKILL.md" else target
    findings = []
    add = lambda level, where, msg: findings.append((level, where, msg))
    name, desc = lint_folder(folder, add)
    if name and a.triggers:
        data = json.loads(pathlib.Path(a.triggers).read_text(encoding="utf-8"))
        t = data.get(name, data) if isinstance(data, dict) else {}
        if not t.get("should") and not t.get("should_not"):
            add("FAIL", "triggers", "%s has no 'should' or 'should_not' prompts for %s" % (a.triggers, name))
        else:
            route_triggers(name, t, skill_docs([folder.parent] + [pathlib.Path(x) for x in a.against]), add)
    for level, where, msg in sorted(findings, key=lambda f: (f[0] != "FAIL", f[1])):
        print("%-4s %-22s %s" % (level, where, msg))
    fails = sum(1 for f in findings if f[0] == "FAIL")
    print("skill-check %s: %d FAIL, %d WARN" % (folder.name, fails, sum(1 for f in findings if f[0] == "WARN")))
    return 1 if fails else 0


SCAFFOLD = {
    "discipline": ("Make the agent <the rule it must follow> even when it is pressed to skip it.",
                   "## The rule\n\n<the rule, stated flatly, with no exceptions clause>\n\n"
                   "## Signs you are about to skip it\n\n- <a phrase or thought that comes right before the skip>\n\n"
                   "## Excuse and reality\n\n| About to be said | What is actually true |\n| --- | --- |\n"
                   "| \"<an excuse a tested agent gave>\" | <why it does not hold> |\n"),
    "technique": ("<what this technique gets done, in one line>",
                  "## Steps\n\n1. <first step, imperative>\n2. <next step>\n\n"
                  "## Example\n\n<one complete example in a real domain>\n"),
    "pattern": ("<the way of seeing the problem, in one line>",
                "## The idea\n\n<the pattern in two or three sentences>\n\n"
                "## It applies when\n\n- <an observable sign>\n\n## It does not apply when\n\n- <a counter-example>\n\n"
                "## Example\n\n<one before and after>\n"),
    "reference": ("<what can be looked up here>",
                  "## Lookup\n\n| Need | Answer |\n| --- | --- |\n| <what someone searches for> | <the fact> |\n"),
}


def scaffold(a):
    folder = pathlib.Path(a.dir) / a.name
    if not NAME_RX.match(a.name):
        print("skill-check new: '%s' must be lowercase letters, digits and hyphens" % a.name)
        return 2
    if folder.exists():
        print("skill-check new: %s already exists" % folder)
        return 2
    purpose, body = SCAFFOLD[a.type]
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: %s\ndescription: Use when <the situation, in the words someone would type>\n---\n\n"
        "# %s\n\n%s\n\n%s\n## Done when\n\n<the observable state that means the job is finished>\n"
        % (a.name, a.name, purpose, body), encoding="utf-8")
    (folder / "triggers.json").write_text(json.dumps({
        "should": ["<a prompt that should load it>", "<another, in different words>", "<a third>"],
        "should_not": ["<a near-miss that belongs to another skill>", "<another>"]}, indent=1) + "\n")
    print("skill-check new: %s skill at %s" % (a.type, folder))
    print("  fill every <slot>, write the scenarios in references/test.md of the forge skill first, then:")
    print("  python3 %s %s --triggers %s" % (HERE, folder, folder / "triggers.json"))
    return 0


# ---------- inside the rubric repo ----------

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


def check_library(argv):
    if not IN_RUBRIC:
        print("skill-check: give a skill folder to check (skill_check.py PATH), or run inside the rubric repo")
        return 2
    ap = argparse.ArgumentParser(prog="skill_check.py", description="check a library skill change by measurement")
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



def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "new":
        ap = argparse.ArgumentParser(prog="skill_check.py new")
        ap.add_argument("name")
        ap.add_argument("--type", choices=sorted(SCAFFOLD), required=True)
        ap.add_argument("--dir", default=".")
        return scaffold(ap.parse_args(argv[1:]))
    looks_like_path = argv and not argv[0].startswith("-") and (
        os.sep in argv[0] or argv[0].endswith("SKILL.md") or (os.path.isdir(argv[0]) and
                                                             os.path.exists(os.path.join(argv[0], "SKILL.md"))))
    if looks_like_path:
        ap = argparse.ArgumentParser(prog="skill_check.py PATH")
        ap.add_argument("target")
        ap.add_argument("--triggers", help="JSON with 'should' and 'should_not' prompts (or keyed by skill name)")
        ap.add_argument("--against", action="append", default=[], help="another skills folder to compete with")
        return check_path(ap.parse_args(argv))
    return check_library(argv)


if __name__ == "__main__":
    sys.exit(main())
