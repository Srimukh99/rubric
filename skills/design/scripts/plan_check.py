#!/usr/bin/env python3
"""plan-check: can someone who has never seen this repo execute the plan?

Reads a plan written in the format of references/blueprint.md against the
repo and the design it implements:

  structure   every task has Files, Consumes, Produces, a test as code, a run
              that fails, an implement step, a run that passes
  interfaces  every name a task consumes, or a test imports, is produced by
              an earlier task or defined in the repo, with the same parameters
  reality     `modify` paths exist, `create` paths do not, line ranges fit,
              `Mirrors` exist, no task needs a later one
  coverage    every Success and Failure modes line of the design is covered
  parallel    `[parallel]` tasks share no file and consume nothing from each other
  gaps        placeholders and lines that decide nothing; test code that does
              not parse; implement steps that are mostly code (WARN)

  --red    copy the working tree to a scratch dir, write each task's test, run
           the plan's own FAIL command, and FAIL any test that already passes
  --waves  which tasks can run at the same time, for delegate
  --json   the parsed tasks, for scripts

Exit 1 on FAIL. Stdlib only.
"""
import argparse
import ast
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import spec_check  # noqa: E402  (same skill: the design file's sections)

TASK = re.compile(r"^##\s+Task\s+(\d+)\s*:\s*(.+?)\s*$")
FIELD = re.compile(r"^(Covers|Files|Mirrors|Consumes|Produces)\s*:\s*(.*)$")
HEADER = re.compile(r"^(Design|Goal|Approach|Stack)\s*:\s*(.*)$")
STEP = re.compile(r"^\s*[-*]\s+\[[ xX]\]\s+(.*)$")
TEST_STEP = re.compile(r"write the failing test in\s+`?([^`:\s]+)`?", re.I)
RUN_STEP = re.compile(r"^run\s+`([^`]+)`.*?expect\s+(fail|pass)(?:\s*:\s*`?([^`]*)`?)?", re.I)
IMPL_STEP = re.compile(r"^implement\s+`([^`]+)`\s+in\s+`?([^`:\s]+)`?", re.I)
SIG = re.compile(r"`([^`]+)`")
PLACEHOLDER = re.compile(r"\bTBD\b|\bTODO\b|\bFIXME\b|\?\?\?|\bTBC\b")
DECIDES_NOTHING = re.compile(
    r"handle (?:the )?edge cases|add (?:appropriate|proper|necessary) (?:validation|error handling|tests)|"
    r"write tests for the above|similar to task \d+|as needed\b|and so on\b|\betc\b\.?|"
    r"implement the rest|fill in the details|whatever is needed", re.I)
DEFINES = r"(?:def|class|function|func|fn|interface|type|struct|enum|trait)\s+{0}\b|" \
          r"(?:const|let|var)\s+{0}\s*=|\b{0}\s*=\s*(?:function|\(|async)|\b{0}\s*:\s*function"
SOURCE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".cs", ".swift", ".php")
TRANSCRIPT_LINES = 25


def parse(text):
    """{'header', 'map', 'tasks'} from a plan in blueprint format."""
    lines = text.splitlines()
    plan = {"header": {}, "map": [], "tasks": []}
    task, step, fenced, code, section = None, None, False, [], None
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            if fenced:
                fenced = False
                if step is not None:
                    step["code"] = "\n".join(code)
                    step["code_line"] = step.get("code_line", i)
            else:
                fenced, code = True, []
                if step is not None:
                    step["lang"] = line.strip().strip("`~").strip().lower()
                    step["code_line"] = i + 1
            continue
        if fenced:
            code.append(raw)
            continue
        m = TASK.match(line)
        if m:
            title = m.group(2)
            task = {"num": int(m.group(1)), "title": re.sub(r"\s*\[parallel\]\s*", "", title, flags=re.I).strip(),
                    "parallel": "[parallel]" in title.lower(), "line": i, "fields": {}, "field_lines": {},
                    "steps": []}
            plan["tasks"].append(task)
            step, section = None, "task"
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            task = step = None if section != "task" else task
            continue
        if task is None:
            m = HEADER.match(line)
            if m and section is None:
                plan["header"][m.group(1)] = (m.group(2).strip(), i)
            elif section == "file map" and line.startswith("|") and not re.match(r"^\|\s*-", line):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells and cells[0].lower() != "file":
                    plan["map"].append((cells[0].strip("`"), cells[1].lower() if len(cells) > 1 else "", i))
            continue
        m = FIELD.match(line)
        if m and step is None:
            task["fields"][m.group(1)] = m.group(2).strip()
            task["field_lines"][m.group(1)] = i
            continue
        m = STEP.match(line)
        if m:
            step = {"text": m.group(1).strip(), "line": i}
            task["steps"].append(step)
    return plan


def signatures(value):
    """[(name, params or None, text)] from a Produces/Consumes value."""
    if not value or value.strip().lower() in ("none", "-", "nothing"):
        return []
    out = []
    for sig in SIG.findall(value):
        m = re.match(r"\s*(?:async\s+)?(?:def\s+|func\s+|fn\s+|class\s+)?([A-Za-z_][\w.]*)\s*(\((.*)\))?", sig)
        if not m:
            continue
        params = None
        if m.group(2) is not None:
            inner, depth, parts, cur = m.group(3), 0, [], ""
            for ch in inner:
                if ch in "([{<":
                    depth += 1
                elif ch in ")]}>":
                    depth -= 1
                if ch == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += ch
            parts.append(cur)
            params = [p.strip().split(":")[0].split("=")[0].strip() for p in parts if p.strip()]
            params = [p for p in params if p not in ("self", "cls")]
        out.append((m.group(1).split(".")[-1], params, sig))
    return out


def files(value):
    """[(kind, path, (start, end) or None)] from a Files value."""
    out = []
    for part in re.split(r"[;,]\s*(?=(?:create|modify|test)\b)", value or ""):
        m = re.match(r"\s*(create|modify|test)\s+`?([^`\s:]+)`?(?::(\d+)-(\d+))?", part, re.I)
        if m:
            rng = (int(m.group(3)), int(m.group(4))) if m.group(3) else None
            out.append((m.group(1).lower(), m.group(2), rng))
    return out


class Repo:
    """What exists in the repo: paths, and where names are defined (lazily)."""

    def __init__(self, root):
        self.root = root
        self._sources = None
        self._defined = {}

    def exists(self, path):
        return os.path.exists(os.path.join(self.root, path))

    def length(self, path):
        with open(os.path.join(self.root, path), encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)

    def sources(self):
        if self._sources is None:
            try:
                names = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=self.root,
                                       capture_output=True, text=True, timeout=60).stdout.splitlines()
            except (OSError, subprocess.TimeoutExpired):
                names = []
            if not names:
                names = [os.path.relpath(os.path.join(d, f), self.root) for d, _, fs in os.walk(self.root)
                         if ".git" not in d for f in fs]
            self._sources = []
            for n in names:
                if n.endswith(SOURCE_EXT):
                    try:
                        if os.path.getsize(os.path.join(self.root, n)) < 1_000_000:
                            with open(os.path.join(self.root, n), encoding="utf-8", errors="replace") as fh:
                                self._sources.append((n, fh.read()))
                    except OSError:
                        pass
        return self._sources

    def names(self):
        """Every name the repo defines, for a "did you mean" on a typo."""
        if not hasattr(self, "_names"):
            rx = re.compile(r"(?:def|class|function|func|fn|interface|type|struct|enum|trait)\s+([A-Za-z_]\w*)")
            self._names = sorted({m for _, text in self.sources() for m in rx.findall(text)})
        return self._names

    def defines(self, name):
        if name not in self._defined:
            rx = re.compile(DEFINES.format(re.escape(name)))
            self._defined[name] = next((p for p, text in self.sources() if rx.search(text)), None)
        return self._defined[name]

    def module(self, dotted):
        """True when a Python module path resolves to a file or package in the repo or stdlib."""
        top = dotted.split(".")[0]
        if top in sys.builtin_module_names or top in getattr(sys, "stdlib_module_names", ()):
            return True
        rel = dotted.replace(".", "/")
        for base in ("", "src/", "lib/"):
            if self.exists(base + rel + ".py") or self.exists(base + rel + "/__init__.py") or self.exists(base + rel):
                return True
        return False


def python_imports(code):
    """[(module, [names])] imported by a test, or None when it does not parse."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, [a.name for a in node.names if a.name != "*"]))
    return out


def check(plan_path, root):
    findings = []

    def add(level, line, msg):
        findings.append((level, plan_path, line, msg))

    try:
        with open(plan_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as err:
        add("FAIL", 0, f"cannot read: {err}")
        return findings, None
    plan = parse(text)
    repo = Repo(root)
    tasks = plan["tasks"]
    head = plan["header"]

    if "Goal" not in head or not head["Goal"][0]:
        add("FAIL", 0, "no 'Goal:' line")
    if not tasks:
        add("FAIL", 0, "no tasks ('## Task 1: <name>')")
        return findings, plan
    for k, t in enumerate(tasks, 1):
        if t["num"] != k:
            add("WARN", t["line"], f"task numbered {t['num']}, expected {k}")

    # Gaps: placeholders and lines that decide nothing, outside code.
    fenced = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        prose = re.sub(r"`[^`]*`", "", line)
        m = PLACEHOLDER.search(prose) or DECIDES_NOTHING.search(prose)
        if m:
            add("FAIL", i, f"decides nothing: '{m.group(0)}' - say exactly what")

    # Design coverage.
    design, success, failure = None, [], []
    if "Design" in head:
        dpath, dline = head["Design"]
        if not repo.exists(dpath):
            add("FAIL", dline, f"design file not found: {dpath}")
        else:
            design = dpath
            with open(os.path.join(root, dpath), encoding="utf-8") as fh:
                found, _ = spec_check.sections(spec_check.strip_code(fh.read().splitlines()))
            success = spec_check.bullets(found.get("Success", []))
            failure = spec_check.bullets(found.get("Failure modes", []))

    produced = {}      # name -> (task num, params, line)
    created = {}       # path -> task num
    touched = {}       # path -> [task nums]
    covered = set()
    repo_hint_names = None

    for t in tasks:
        f, fl = t["fields"], t["field_lines"]
        for need in ("Files", "Consumes", "Produces"):
            if need not in f:
                add("FAIL", t["line"], f"Task {t['num']}: no '{need}:' line")
        if design and "Covers" not in f:
            add("FAIL", t["line"], f"Task {t['num']}: no 'Covers:' line (which design lines does it make true?)")
        for m in re.finditer(r"(Success|Failure modes)\s+(\d+)", f.get("Covers", ""), re.I):
            kind, n = m.group(1).capitalize(), int(m.group(2))
            pool = success if kind == "Success" else failure
            if design and not 1 <= n <= len(pool):
                add("FAIL", fl.get("Covers", t["line"]), f"Task {t['num']}: covers {kind} {n}, but the design has {len(pool)}")
            covered.add((kind, n))

        if f.get("Mirrors"):
            mpath = f["Mirrors"].strip("` ").split()[0]
            if not repo.exists(mpath):
                add("FAIL", fl["Mirrors"], f"Task {t['num']}: mirrors {mpath}, which does not exist")

        # Files: reality and order.
        for kind, path, rng in files(f.get("Files", "")):
            touched.setdefault(path, []).append(t["num"])
            here = repo.exists(path)
            if kind == "create":
                if here:
                    add("FAIL", fl["Files"], f"Task {t['num']}: creates {path}, which already exists (modify it?)")
                elif path in created:
                    add("FAIL", fl["Files"], f"Task {t['num']}: creates {path}, already created by Task {created[path]}")
                else:
                    created[path] = t["num"]
            elif kind == "modify":
                if not here and path not in created:
                    later = next((u["num"] for u in tasks if u["num"] > t["num"] and
                                  any(k == "create" and p == path for k, p, _ in files(u["fields"].get("Files", "")))), None)
                    add("FAIL", fl["Files"], f"Task {t['num']}: modifies {path}, " +
                        (f"which Task {later} creates later" if later else "which does not exist"))
                elif here and rng and rng[1] > repo.length(path):
                    add("FAIL", fl["Files"], f"Task {t['num']}: {path}:{rng[0]}-{rng[1]} is past its end "
                                             f"({repo.length(path)} lines)")
            elif kind == "test" and not here and path not in created:
                created[path] = t["num"]

        # Interfaces: consumes.
        for name, params, sig in signatures(f.get("Consumes", "")):
            if name in produced:
                pnum, pparams, _ = produced[name]
                if params is not None and pparams is not None and len(params) != len(pparams):
                    add("FAIL", fl["Consumes"], f"Task {t['num']}: consumes `{sig}`, but Task {pnum} produces "
                                                f"{name} with {len(pparams)} parameter(s)")
                continue
            later = next((u["num"] for u in tasks if u["num"] > t["num"] and
                          any(n == name for n, _, _ in signatures(u["fields"].get("Produces", "")))), None)
            if later:
                add("FAIL", fl["Consumes"], f"Task {t['num']}: consumes {name}, which Task {later} produces later")
            elif not repo.defines(name):
                known = list(produced) + [n for u in tasks for n, _, _ in signatures(u["fields"].get("Produces", ""))]
                near = difflib.get_close_matches(name, known, 1, 0.75) or \
                    difflib.get_close_matches(name, repo.names(), 1, 0.8)
                add("FAIL", fl["Consumes"], f"Task {t['num']}: consumes {name}, which no earlier task produces and "
                                            f"the repo does not define" + (f" (did you mean {near[0]}?)" if near else ""))

        # Steps.
        kinds = []
        for s in t["steps"]:
            txt = s["text"]
            if TEST_STEP.search(txt):
                s["kind"], s["path"] = "test", TEST_STEP.search(txt).group(1)
                if not s.get("code", "").strip():
                    add("FAIL", s["line"], f"Task {t['num']}: test step with no test code")
                elif s["path"].endswith(".py") or s.get("lang") in ("python", "py"):
                    imports = python_imports(s["code"])
                    if imports is None:
                        try:
                            ast.parse(s["code"])
                        except SyntaxError as err:
                            add("FAIL", s.get("code_line", s["line"]) + (err.lineno or 1) - 1,
                                f"Task {t['num']}: test code does not parse: {err.msg}")
                    else:
                        own = {n for n, _, _ in signatures(f.get("Produces", ""))}
                        for mod, names in imports:
                            for n in names:
                                if n in own or n in produced or repo.defines(n) or repo.module(mod + "." + n):
                                    continue
                                if not repo.module(mod) and not any(mod.split(".")[-1] in p for p in created):
                                    add("FAIL", s.get("code_line", s["line"]),
                                        f"Task {t['num']}: test imports {n} from {mod}, which neither the plan nor the repo provides")
                                else:
                                    add("FAIL", s.get("code_line", s["line"]),
                                        f"Task {t['num']}: test imports {n}, which no task up to this one produces"
                                        + (f" (Produces says {', '.join(sorted(own))})" if own else ""))
                if s["path"] not in touched:
                    add("WARN", s["line"], f"Task {t['num']}: writes a test to {s['path']}, which its Files line does not list")
            elif RUN_STEP.search(txt):
                m = RUN_STEP.search(txt)
                s["kind"], s["cmd"], s["expect"], s["reason"] = "run", m.group(1), m.group(2).lower(), (m.group(3) or "").strip()
                if s["expect"] == "fail" and not s["reason"]:
                    add("WARN", s["line"], f"Task {t['num']}: a FAIL with no reason; name the message, so failing "
                                           f"for the wrong reason shows")
            elif IMPL_STEP.search(txt):
                m = IMPL_STEP.search(txt)
                s["kind"], s["sig"], s["path"] = "impl", m.group(1), m.group(2)
                body = [l for l in s.get("code", "").splitlines() if l.strip()]
                if len(body) > TRANSCRIPT_LINES:
                    add("WARN", s["line"], f"Task {t['num']}: implement step carries {len(body)} lines of code - "
                                           f"that is the code, not a plan; give the signature and the choice")
                own = [n for n, _, _ in signatures(f.get("Produces", ""))]
                name = (signatures("`%s`" % s["sig"]) or [(None,)])[0][0]
                if name and own and name not in own:
                    add("WARN", s["line"], f"Task {t['num']}: implements {name}, which its Produces line does not list")
            elif re.match(r"^commit\b", txt, re.I):
                s["kind"] = "commit"
            else:
                s["kind"] = "other"
            kinds.append(s["kind"])
        seq = [k if k != "run" else "run-" + s["expect"] for k, s in zip(kinds, t["steps"])]
        need = [("test", "a test step with the test as code ('Write the failing test in <path>:')"),
                ("run-fail", "a run that fails first ('Run `cmd`. Expect FAIL: `reason`')"),
                ("impl", "an implement step ('Implement `signature` in <path>: ...')"),
                ("run-pass", "a run that passes after ('Run `cmd`. Expect PASS')")]
        for k, what in need:
            if k not in seq:
                add("FAIL", t["line"], f"Task {t['num']}: missing {what}")
        if all(k in seq for k, _ in need):
            if seq.index("run-fail") > seq.index("impl"):
                add("FAIL", t["line"], f"Task {t['num']}: the failing run comes after the implementation")
            if max(i for i, k in enumerate(seq) if k == "run-pass") < seq.index("impl"):
                add("FAIL", t["line"], f"Task {t['num']}: no passing run after the implementation")
        if "commit" not in seq:
            add("WARN", t["line"], f"Task {t['num']}: no commit step")
        if len(t["steps"]) > 7:
            add("WARN", t["line"], f"Task {t['num']}: {len(t['steps'])} steps - probably two tasks")

        for name, params, sig in signatures(f.get("Produces", "")):
            if name in produced and produced[name][1] is not None and params is not None \
                    and len(produced[name][1]) != len(params):
                add("FAIL", fl["Produces"], f"Task {t['num']}: produces {name} with {len(params)} parameter(s); "
                                            f"Task {produced[name][0]} produced it with {len(produced[name][1])}")
            produced.setdefault(name, (t["num"], params, fl.get("Produces")))

    # Coverage of the design.
    for kind, pool in (("Success", success), ("Failure modes", failure)):
        for n, (line, text) in enumerate(pool, 1):
            if (kind, n) not in covered:
                add("FAIL", 0, f"{design} {kind} {n} is covered by no task: {text[:70]}")

    # File map against the tasks.
    mapped = {p for p, _, _ in plan["map"]}
    if plan["map"]:
        for path in touched:
            if path not in mapped:
                add("WARN", 0, f"{path} is changed by Task {touched[path][0]} but missing from the file map")
        for path, _, line in plan["map"]:
            if path not in touched:
                add("WARN", line, f"file map lists {path}, which no task touches")
    else:
        add("WARN", 0, "no file map: list each file and its one responsibility before the tasks")

    # Parallel tasks.
    par = [t for t in tasks if t["parallel"]]
    for i, a in enumerate(par):
        fa = {p for _, p, _ in files(a["fields"].get("Files", ""))}
        pa = {n for n, _, _ in signatures(a["fields"].get("Produces", ""))}
        for b in par[i + 1:]:
            fb = {p for _, p, _ in files(b["fields"].get("Files", ""))}
            cb = {n for n, _, _ in signatures(b["fields"].get("Consumes", ""))}
            if fa & fb:
                add("FAIL", b["line"], f"Tasks {a['num']} and {b['num']} are [parallel] but both touch "
                                       f"{', '.join(sorted(fa & fb))}")
            if pa & cb:
                add("FAIL", b["line"], f"Task {b['num']} is [parallel] but consumes {', '.join(sorted(pa & cb))} "
                                       f"from Task {a['num']}")
    return findings, plan


def waves(plan):
    """Layers of tasks that can run together: no shared file, no interface between them."""
    tasks = plan["tasks"]
    deps = {t["num"]: set() for t in tasks}
    for j, b in enumerate(tasks):
        fb = {p for _, p, _ in files(b["fields"].get("Files", ""))}
        cb = {n for n, _, _ in signatures(b["fields"].get("Consumes", ""))}
        for a in tasks[:j]:
            fa = {p for _, p, _ in files(a["fields"].get("Files", ""))}
            pa = {n for n, _, _ in signatures(a["fields"].get("Produces", ""))}
            if fa & fb or pa & cb:
                deps[b["num"]].add(a["num"])
    level = {}
    for t in tasks:
        level[t["num"]] = 1 + max((level[d] for d in deps[t["num"]]), default=0)
    out = {}
    for n, lv in level.items():
        out.setdefault(lv, []).append(n)
    return [out[k] for k in sorted(out)]


def red(plan, root, timeout):
    """Write each task's test into a copy of the working tree and run its FAIL command."""
    findings = []
    tmp = tempfile.mkdtemp(prefix="plan-red-")
    try:
        try:
            names = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                                   capture_output=True, text=True, timeout=60).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            names = []
        for n in names or []:
            src = os.path.join(root, n)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(os.path.join(tmp, n)), exist_ok=True)
                shutil.copy2(src, os.path.join(tmp, n))
        if not names:
            shutil.rmtree(tmp)
            shutil.copytree(root, tmp, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
        produced_by_plan = set()
        env = {**os.environ, "PYTHONBREAKPOINT": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        for t in plan["tasks"]:
            consumes_plan = {n for n, _, _ in signatures(t["fields"].get("Consumes", ""))} & produced_by_plan
            for s in t["steps"]:
                if s.get("kind") == "test" and s.get("code"):
                    path = os.path.join(tmp, s["path"])
                    os.makedirs(os.path.dirname(path) or tmp, exist_ok=True)
                    mode = "a" if os.path.exists(path) else "w"
                    with open(path, mode, encoding="utf-8") as fh:
                        fh.write(("\n\n" if mode == "a" else "") + s["code"].rstrip() + "\n")
                elif s.get("kind") == "run" and s.get("expect") == "fail":
                    try:
                        p = subprocess.run(s["cmd"], shell=True, cwd=tmp, capture_output=True, text=True,
                                           errors="replace", timeout=timeout, env=env)
                        rc, out = p.returncode, p.stdout + p.stderr
                    except subprocess.TimeoutExpired:
                        findings.append(("FAIL", s["line"], f"Task {t['num']}: `{s['cmd']}` timed out after {timeout}s"))
                        continue
                    tail = (out.strip().splitlines() or [""])[-1][:100]
                    if rc == 0:
                        findings.append(("FAIL", s["line"], f"Task {t['num']}: the test passes before its code exists - "
                                                            f"it checks nothing new (`{s['cmd']}`)"))
                    elif rc == 127 or "command not found" in out or "No module named pytest" in out:
                        findings.append(("FAIL", s["line"], f"Task {t['num']}: `{s['cmd']}` cannot run here: {tail}"))
                    elif s.get("reason") and not consumes_plan and s["reason"] not in out:
                        findings.append(("WARN", s["line"], f"Task {t['num']}: fails, but not with "
                                                            f"`{s['reason']}`: {tail}"))
            produced_by_plan |= {n for n, _, _ in signatures(t["fields"].get("Produces", ""))}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="check that a plan can be executed cold")
    ap.add_argument("plan")
    ap.add_argument("--repo", default=".", help="repo the plan is for (default: .)")
    ap.add_argument("--red", action="store_true", help="prove each task's test fails before its code exists")
    ap.add_argument("--waves", action="store_true", help="print the tasks that can run at once")
    ap.add_argument("--json", action="store_true", help="print the parsed tasks as JSON")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per command with --red")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.repo)
    findings, plan = check(a.plan, root)
    if a.red and plan and plan["tasks"] and not any(f[0] == "FAIL" for f in findings):
        findings += [(lv, a.plan, line, msg) for lv, line, msg in red(plan, root, a.timeout)]
    elif a.red:
        findings.append(("WARN", a.plan, 0, "--red skipped: fix the FAILs first"))
    if a.json and plan:
        print(json.dumps([{"num": t["num"], "title": t["title"], "parallel": t["parallel"],
                           "files": files(t["fields"].get("Files", "")),
                           "produces": [s for _, _, s in signatures(t["fields"].get("Produces", ""))],
                           "consumes": [s for _, _, s in signatures(t["fields"].get("Consumes", ""))],
                           "runs": [s.get("cmd") for s in t["steps"] if s.get("kind") == "run"]}
                          for t in plan["tasks"]], indent=1))
        return 1 if any(f[0] == "FAIL" for f in findings) else 0
    for level, path, line, msg in sorted(findings, key=lambda f: (f[0] != "FAIL", f[2])):
        print(f"{level:<5} {path}:{line}  {msg}" if line else f"{level:<5} {path}  {msg}")
    if a.waves and plan and plan["tasks"]:
        for i, w in enumerate(waves(plan), 1):
            print(f"wave {i}: " + ", ".join(f"Task {n}" for n in w))
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = sum(1 for f in findings if f[0] == "WARN")
    n = len(plan["tasks"]) if plan else 0
    print(f"plan-check: {fails} FAIL, {warns} WARN, {n} task(s)" + (", tests proven red" if a.red and not fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
