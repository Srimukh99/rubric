#!/usr/bin/env python3
"""spec-check: catch what a design file must not carry into approval.

Checks a design written from the template in references/shape.md: the size and
status lines, every section the size needs, placeholders left in, success lines
with nothing to measure, a rollout with no way back, open questions with no
owner, and Mermaid blocks that will not render. WARNs on wording that reads two
ways and on a structural design with no diagram. Exit 1 on FAIL.

The Mermaid lint is a floor, not a parser. It FAILs what will not render, or
will not draw what was written: an unknown diagram type, unbalanced brackets,
braces or quotes, a block opened without its `end`, a placeholder inside a
diagram, a sequence message with no text. (Mermaid draws `[* --> a` without
complaint, as a box labelled "[*" instead of the start marker.) The real
renderer catches more.

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
    "structural": ["Problem", "Success", "Non-goals", "Assumptions", "Approaches considered", "Data model", "Interfaces",
                   "Flow", "Failure modes", "Testing", "Rollout and undo", "Open questions"],
    "bounded": ["Problem", "Success", "Testing", "Rollout and undo"],
    "probe": ["Problem"],
}
MAY_BE_EMPTY = {"Open questions", "Assumptions"}
# Words that let two engineers build two different things.
TWO_READINGS = re.compile(r"\betc\b\.?|\band/or\b|\bas (?:needed|appropriate|required)\b|\bif possible\b|"
                          r"\bwhere (?:possible|needed)\b|\bappropriate(?:ly)?\b|\bgracefully\b|\bproperly\b|"
                          r"\breasonabl[ey]\b|\bsufficient(?:ly)?\b|\bvarious\b|\bsome kind of\b", re.I)
TWO_READINGS_IN = ("Success", "Interfaces", "Data model", "Flow", "Failure modes", "Testing", "Rollout and undo")
MERMAID_TYPES = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2", "erDiagram",
                 "classDiagram", "gantt", "journey", "pie", "mindmap", "timeline", "gitGraph", "quadrantChart",
                 "requirementDiagram", "C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment",
                 "sankey-beta", "xychart-beta", "block-beta", "packet-beta", "architecture-beta", "kanban", "radar-beta")
# Blocks closed by a line reading `end`, per diagram type.
BLOCK_OPENERS = {"sequenceDiagram": r"alt|opt|loop|par|critical|break|rect|box",
                 "flowchart": r"subgraph", "graph": r"subgraph"}
CARDINALITY = re.compile(r"[|}][|o](?:--|\.\.)[o|][|{]")
SEQ_ARROW = re.compile(r"^\s*[\w\s\"]+?\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))[+-]?\s*[\w\"]")
SEQ_KEYWORD = re.compile(r"^\s*(?:participant|actor|alt|else|opt|loop|par|and|critical|break|rect|end|note|"
                         r"activate|deactivate|autonumber|box|create|destroy|title|%%)\b", re.I)
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


def mermaid_blocks(raw):
    """[(line number of the opening fence, [(lineno, text), ...])] for ```mermaid blocks."""
    blocks, current = [], None
    for i, line in enumerate(raw, 1):
        fence = line.strip()
        if current is None and re.match(r"^```\s*mermaid\b", fence):
            current = (i, [])
        elif current is not None and fence.startswith("```"):
            blocks.append(current)
            current = None
        elif current is not None:
            current[1].append((i, line))
    if current is not None:
        blocks.append(current)
    return blocks


def lint_mermaid(start, body):
    """FAIL lines for one Mermaid block: what will not render, will not draw what was written, or is unfinished."""
    out = []
    lines = [(i, l) for i, l in body if l.strip() and not l.strip().startswith("%%")]
    if not lines:
        return [(start, "empty Mermaid block")]
    kind = lines[0][1].split()[0]
    if kind not in MERMAID_TYPES:
        out.append((lines[0][0], f"unknown Mermaid diagram type: {kind}"))
    pairs = {"(": ")", "[": "]"}
    braces = 0     # {} may span lines: entity and class bodies
    for i, line in lines:
        if line.count('"') % 2:
            out.append((i, "unbalanced quote in Mermaid line"))
            continue
        # Quoted text is a label, and ||--o{ is cardinality, not a bracket.
        bare = CARDINALITY.sub(" ", re.sub(r'"[^"]*"', "", line))
        braces += bare.count("{") - bare.count("}")
        stack, bad = [], False
        for ch in bare:
            if ch in pairs:
                stack.append(pairs[ch])
            elif ch in pairs.values():
                if not stack or stack.pop() != ch:
                    bad = True
                    break
        if bad or stack:
            out.append((i, "unbalanced brackets in Mermaid line"))
        m = PLACEHOLDER.search(re.sub(r"<[a-z][a-z0-9 _/.-]{0,40}>", "", line))
        if m:
            out.append((i, f"placeholder left in a diagram: {m.group(0)}"))
        if kind == "sequenceDiagram" and SEQ_ARROW.match(line) and not SEQ_KEYWORD.match(line) and ":" not in line:
            out.append((i, "sequence message with no text (add ': <what is sent>')"))
    if braces:
        out.append((start, "unbalanced braces in Mermaid block"))
    opener = BLOCK_OPENERS.get(kind)
    if opener:
        depth = 0
        for i, line in lines[1:]:
            word = line.split()[0] if line.split() else ""
            if re.fullmatch(opener, word):
                depth += 1
            elif word == "end":
                depth -= 1
                if depth < 0:
                    out.append((i, "'end' with no block to close"))
                    depth = 0
        if depth > 0:
            out.append((start, f"{depth} block(s) opened with no 'end'"))
    return out


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

    for name in TWO_READINGS_IN:
        for i, text in found.get(name, []):
            for m in TWO_READINGS.finditer(re.sub(r"`code`", "", text)):
                add("WARN", i, f"reads two ways in ## {name}: '{m.group(0)}' - say which")

    blocks = mermaid_blocks(raw)
    for start, body in blocks:
        for i, msg in lint_mermaid(start, body):
            add("FAIL", i, msg)
    if size == "structural" and not blocks:
        add("WARN", 0, "no diagram: a flow with three or more parts, or states, reads better drawn "
                       "(references/sketch.md)")

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
