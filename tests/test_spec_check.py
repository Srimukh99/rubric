"""spec-check: a clean design passes, and each defect it claims to catch is caught."""
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "design" / "scripts"))
import spec_check as SC  # noqa: E402

GOOD = """# Retry billing calls

Size: structural
Status: draft

## Problem
About 2% of calls to the billing API fail with a 503 and the user sees an error page.

## Success
- Billing errors shown to users fall from 2% to under 0.1% of checkouts over 7 days.
- `pytest tests/test_billing_retry.py` passes, including the timeout case.

## Non-goals
- Retrying calls to any other vendor.

## Assumptions
- Billing honours an idempotency key on retried charges (their docs say so; not yet tested).

## Approaches considered
1. Retry in the client with backoff. Chosen: smallest change, undone by a flag.
2. A queue in front of billing. Rejected: a new dependency for a 2% problem.

## Data model
No change.

## Interfaces
`charge(order, attempt=1)` gains the attempt counter; callers are unchanged.

## Flow
```mermaid
sequenceDiagram
  App->>Billing: charge (<order>)
  Billing-->>App: 503
  App->>Billing: charge, attempt 2 after 200 ms
```

## Failure modes
- Billing down for minutes: three attempts, then the existing error page.
- A retried charge that already succeeded: the idempotency key makes it a no-op.

## Testing
One test per failure mode above, against a fake billing server.

## Rollout and undo
Behind the `billing_retry` flag at 5%, then 100%. Undo: turn the flag off.

## Open questions
- Is three attempts too many at peak? owner: Dana
"""


def run(text, name="d.md"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, name)
        pathlib.Path(p).write_text(text)
        return [(level, msg) for level, _, _, msg in SC.check(p)]


def fails(text):
    return [m for level, m in run(text) if level == "FAIL"]


class CleanDesignPasses(unittest.TestCase):
    def test_good_structural_design_is_clean(self):
        self.assertEqual(run(GOOD), [])

    def test_code_blocks_and_inline_code_are_not_placeholders(self):
        """`<order>` in a diagram or `TODO` in inline code is content, not a gap."""
        self.assertEqual(fails(GOOD.replace("No change.", "No change; the `TODO` column stays.")), [])

    def test_approved_with_a_resolved_question(self):
        text = GOOD.replace("Status: draft", "Status: approved by Dana on 2026-10-04").replace(
            "owner: Dana", "resolved: three, measured at peak")
        self.assertEqual(fails(text), [])

    def test_bounded_needs_only_its_sections(self):
        text = ("Size: bounded\nStatus: draft\n## Problem\nX fails.\n## Success\n`pytest -k x` passes.\n"
                "## Testing\nOne test.\n## Rollout and undo\nRevert the commit.\n")
        self.assertEqual(fails(text), [])


class DefectsAreCaught(unittest.TestCase):
    def test_placeholders(self):
        for gap in ("TBD", "TODO: decide", "???", "<owner name>"):
            got = fails(GOOD.replace("No change.", "No change. " + gap))
            self.assertTrue(any("placeholder" in m for m in got), gap)

    def test_missing_and_empty_sections(self):
        self.assertIn("missing section: ## Failure modes",
                      fails(GOOD.replace("## Failure modes", "## Risks")))
        self.assertTrue(any(m.startswith("empty section: ## Data model")
                            for m in fails(GOOD.replace("No change.", ""))))

    def test_success_with_nothing_to_measure(self):
        got = run(GOOD.replace("- Billing errors shown to users fall from 2% to under 0.1% of checkouts over 7 days.",
                               "- Billing feels more reliable."))
        self.assertIn(("FAIL", "success line with nothing to measure (no number, command or test)"), got)

    def test_vague_success_word_warns(self):
        got = run(GOOD.replace("including the timeout case", "and checkout is faster"))
        self.assertIn(("WARN", "vague success word with no number: faster"), got)

    def test_rollout_without_undo(self):
        got = fails(GOOD.replace("Behind the `billing_retry` flag at 5%, then 100%. Undo: turn the flag off.",
                                 "Ship to everyone on Monday."))
        self.assertIn("rollout says how to ship, not how to undo", got)

    def test_open_question_needs_an_owner(self):
        got = fails(GOOD.replace(" owner: Dana", ""))
        self.assertIn("open question with no owner (add 'owner: <name>')", got)

    def test_approval_with_open_question(self):
        got = fails(GOOD.replace("Status: draft", "Status: approved by Dana on 2026-10-04"))
        self.assertIn("approved with this question still open", got)

    def test_size_and_status_lines(self):
        self.assertTrue(any("no 'Size:' line" in m for m in fails(GOOD.replace("Size: structural\n", ""))))
        self.assertTrue(any("unknown size" in m for m in fails(GOOD.replace("structural", "huge", 1))))
        self.assertTrue(any("status must be" in m for m in fails(GOOD.replace("Status: draft", "Status: approved"))))

    def test_none_is_an_empty_open_questions_list(self):
        self.assertEqual(fails(GOOD.replace("- Is three attempts too many at peak? owner: Dana", "None.")), [])


class CommandLine(unittest.TestCase):
    def test_exit_codes(self):
        import contextlib, io
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "good.md"), os.path.join(d, "bad.md")
            pathlib.Path(good).write_text(GOOD)
            pathlib.Path(bad).write_text(GOOD.replace("No change.", "TBD"))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(SC.main([good]), 0)
                self.assertEqual(SC.main([good, bad]), 1)
            self.assertIn("spec-check: 1 FAIL, 0 WARN, 2 file(s)", out.getvalue())


class Diagrams(unittest.TestCase):
    """The Mermaid lint is a floor: what will certainly not render, or is unfinished."""

    def flow(self, diagram):
        return GOOD.replace("""sequenceDiagram
  App->>Billing: charge (<order>)
  Billing-->>App: 503
  App->>Billing: charge, attempt 2 after 200 ms""", diagram)

    def test_good_diagram_kinds_pass(self):
        for d in ("flowchart LR\n  A[checkout] -->|charge| B[(queue)]",
                  "stateDiagram-v2\n  [*] --> pending\n  pending --> charged: 200",
                  "erDiagram\n  ORDER ||--o{ ATTEMPT : has\n  ATTEMPT }|..|| KEY : uses\n  ORDER {\n    string id\n  }",
                  "sequenceDiagram\n  participant A as app\n  alt 503\n    A->>B: retry\n  end"):
            self.assertEqual(fails(self.flow(d)), [], d)

    def test_unknown_type(self):
        self.assertIn("unknown Mermaid diagram type: sequenceDiagramz",
                      fails(self.flow("sequenceDiagramz\n  A->>B: hi")))

    def test_unbalanced_brackets_and_quotes(self):
        self.assertIn("unbalanced brackets in Mermaid line", fails(self.flow("flowchart LR\n  A[checkout --> B")))
        self.assertIn("unbalanced quote in Mermaid line", fails(self.flow('flowchart LR\n  A["checkout] --> B')))

    def test_block_without_end(self):
        self.assertIn("1 block(s) opened with no 'end'",
                      fails(self.flow("sequenceDiagram\n  alt 503\n    A->>B: retry")))
        self.assertIn("1 block(s) opened with no 'end'",
                      fails(self.flow('flowchart LR\n  subgraph A["option A"]\n    X --> Y')))
        self.assertIn("'end' with no block to close", fails(self.flow("sequenceDiagram\n  A->>B: hi\n  end")))

    def test_start_marker_typo_fails_although_mermaid_draws_it(self):
        """Mermaid renders `[* --> a` as a box labelled "[*": a FAIL is right."""
        self.assertIn("unbalanced brackets in Mermaid line", fails(self.flow("stateDiagram-v2\n  [* --> a")))

    def test_unclosed_entity_body(self):
        self.assertIn("unbalanced braces in Mermaid block", fails(self.flow("erDiagram\n  ORDER {\n    string id")))

    def test_brackets_inside_quotes_are_text(self):
        self.assertEqual(fails(self.flow('flowchart LR\n  A["charge (retry]"] --> B')), [])

    def test_placeholder_inside_a_diagram(self):
        self.assertIn("placeholder left in a diagram: TBD", fails(self.flow("flowchart LR\n  A --> B[TBD]")))

    def test_sequence_message_needs_text(self):
        self.assertIn("sequence message with no text (add ': <what is sent>')",
                      fails(self.flow("sequenceDiagram\n  A->>B")))

    def test_empty_block(self):
        self.assertIn("empty Mermaid block", fails(self.flow("")))

    def test_structural_without_a_diagram_warns(self):
        text = GOOD.replace("```mermaid", "```text")
        self.assertIn(("WARN", "no diagram: a flow with three or more parts, or states, reads better drawn "
                               "(references/sketch.md)"), run(text))
        self.assertEqual(fails(text), [])

    def test_bounded_without_a_diagram_does_not_warn(self):
        text = ("Size: bounded\nStatus: draft\n## Problem\nX fails.\n## Success\n`pytest -k x` passes.\n"
                "## Testing\nOne test.\n## Rollout and undo\nRevert the commit.\n")
        self.assertEqual(run(text), [])


class TwoReadings(unittest.TestCase):
    def test_vague_wording_warns_in_requirement_sections(self):
        got = run(GOOD.replace("then the existing error page.", "then fail gracefully, etc."))
        self.assertIn(("WARN", "reads two ways in ## Failure modes: 'gracefully' - say which"), got)
        self.assertIn(("WARN", "reads two ways in ## Failure modes: 'etc.' - say which"), got)

    def test_not_in_problem_or_approaches(self):
        """Describing today's mess vaguely is fine; requiring something vaguely is not."""
        self.assertEqual(run(GOOD.replace("sees an error page.", "sees errors, timeouts, etc.")), [])

    def test_assumptions_section_is_required_but_may_say_none(self):
        self.assertIn("missing section: ## Assumptions", fails(GOOD.replace("## Assumptions", "## Notes")))
        self.assertEqual(fails(GOOD.replace(
            "- Billing honours an idempotency key on retried charges (their docs say so; not yet tested).", "")), [])


if __name__ == "__main__":
    unittest.main()
