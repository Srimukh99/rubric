#!/usr/bin/env python3
"""spec-check: catch what a design file must not carry into approval.

Checks a design written from the template in references/shape.md: the size and
status lines, every section the size needs, placeholders left in, success lines
with nothing to measure, a rollout with no way back, and open questions with no
owner. Exit 1 on FAIL.

What it cannot check - contradictions, coverage, terms used before they are
defined - is listed in shape.md for a human read. This only clears the floor.

Run: python3 spec_check.py docs/designs/<file>.md [...]
Stdlib only.
"""
import argparse
import re
import sys

SIZES = ("probe", "bounded", "structural")
REQUIRED = {
    "structural": ["Problem", "Success", "Non-goals", "Approaches considered", "Data model", "Interfaces",
                   "Flow", "Failure modes", "Testing", "Rollout and undo", "Open questions"],
    "bounded": ["Problem", "Success", "Testing", "Rollout and undo"],
    "probe": ["Problem"],
}
MAY_BE_EMPTY = {"Open questions"}
PLACEHOLDER = re.compile(r"\b(?:TBD|TODO|FIXME|XXX|TBC)\b|\?\?\?|<[a-z][a-z0-9 _/.-]{0,40}>|\blorem ipsum\b", re.I)
MEASURABLE = re.compile(r"\d|`[^`]+`|\btests?\b|\bassert", re.I)
VAGUE = re.compile(r"\b(?:fast(?:er)?|robust|scalable|seamless(?:ly)?|user.friendly|better|improved|"
                   r"efficient|intuitive|reliable|easy|simple)\b", re.I)
UNDO = re.compile(r"\b(?:undo|roll ?back|revert|disable|feature flag|flag off|kill switch|restore|back out)\b", re.I)
OWNED = re.compile(r"\b(?:owner|owned by|resolved|decided|answer(?:ed)?)\b\s*[:=-]?", re.I)
NONE = re.compile(r"^\s*(?:none\.?|n/a\.?|-)\s*$", re.I)
STATUS = re.compile(r"^Status:\s*(draft|approved by \S.*? on \d{4}-\d{2}-\d{2})\s*$", re.I)


def strip_code(lines):
    """Neutralise fenced blocks and inline code, keeping line numbers.

    Code is content - a section holding only a diagram is not empty - but what
    it says is not prose, so `<order>` in a diagram is not a placeholder.
    """
    out, fenced = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("`code`")
            continue
        out.append("`code`" if fenced and line.strip() else "" if fenced else re.sub(r"`[^`]*`", "`code`", line))
    return out


def sections(lines):
    """{heading: [(lineno, text), ...]} for every `## ` heading, plus where each starts."""
    found, starts, current = {}, {}, None
    for i, line in enumerate(lines, 1):
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if m:
            current = m.group(1).strip()
            found[current], starts[current] = [], i
        elif current is not None and line.strip():
            found[current].append((i, line.strip()))
    return found, starts


def bullets(body):
    """Bullet or numbered items, or the paragraph lines when there are none."""
    items = [(i, t) for i, t in body if re.match(r"^(?:[-*+]|\d+[.)])\s+", t)]
    return items or [(i, t) for i, t in body if not t.startswith("|") and not t.startswith("```")]


def check(path):
    findings = []

    def add(level, lineno, msg):
        findings.append((level, path, lineno, msg))

    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except OSError as err:
        add("FAIL", 0, f"cannot read: {err}")
        return findings
    lines = strip_code(raw)

    size_line = next(((i, l) for i, l in enumerate(lines, 1) if re.match(r"^Size:", l, re.I)), None)
    size = None
    if not size_line:
        add("FAIL", 0, f"no 'Size:' line ({', '.join(SIZES)})")
    else:
        word = size_line[1].split(":", 1)[1].strip().lower()
        if word in SIZES:
            size = word
        else:
            add("FAIL", size_line[0], f"unknown size '{word}' ({', '.join(SIZES)})")

    status_line = next(((i, l) for i, l in enumerate(lines, 1) if re.match(r"^Status:", l, re.I)), None)
    approved = False
    if not status_line:
        add("FAIL", 0, "no 'Status:' line (draft, or 'approved by <name> on YYYY-MM-DD')")
    elif not STATUS.match(status_line[1]):
        add("FAIL", status_line[0], "status must be 'draft' or 'approved by <name> on YYYY-MM-DD'")
    else:
        approved = status_line[1].split(":", 1)[1].strip().lower().startswith("approved")

    for i, line in enumerate(lines, 1):
        for m in PLACEHOLDER.finditer(line):
            add("FAIL", i, f"placeholder left in: {m.group(0)}")

    found, starts = sections(lines)
    for name in REQUIRED.get(size, REQUIRED["structural"] if size is None else []):
        if name not in found:
            add("FAIL", 0, f"missing section: ## {name}")
        elif not found[name] and name not in MAY_BE_EMPTY:
            add("FAIL", starts[name], f"empty section: ## {name}")

    for i, text in bullets(found.get("Success", [])):
        if not MEASURABLE.search(text):
            add("FAIL", i, "success line with nothing to measure (no number, command or test)")
        elif VAGUE.search(text) and not re.search(r"\d", text):
            add("WARN", i, f"vague success word with no number: {VAGUE.search(text).group(0)}")

    if "Rollout and undo" in found and found["Rollout and undo"]:
        if not any(UNDO.search(t) for _, t in found["Rollout and undo"]):
            add("FAIL", starts["Rollout and undo"], "rollout says how to ship, not how to undo")

    open_items = [(i, t) for i, t in found.get("Open questions", []) if not NONE.match(t)]
    for i, text in bullets(open_items):
        if approved and not re.search(r"\bresolved\b|\bdecided\b|\banswer(?:ed)?\b", text, re.I):
            add("FAIL", i, "approved with this question still open")
        elif not OWNED.search(text):
            add("FAIL", i, "open question with no owner (add 'owner: <name>')")
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="check a design file before asking for approval")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    findings = [f for p in a.files for f in check(p)]
    for level, path, lineno, msg in sorted(findings, key=lambda f: (f[1], f[0] != "FAIL", f[2])):
        print(f"{level:<5} {path}:{lineno}  {msg}" if lineno else f"{level:<5} {path}  {msg}")
    fails = sum(1 for f in findings if f[0] == "FAIL")
    warns = sum(1 for f in findings if f[0] == "WARN")
    print(f"spec-check: {fails} FAIL, {warns} WARN, {len(a.files)} file(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
