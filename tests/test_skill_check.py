"""skill_check.py: description rules, trigger routing, and the regression guard against the base."""
import contextlib
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "forge" / "scripts"))
import skill_check as SC  # noqa: E402


class Repo(unittest.TestCase):
    def test_every_skill_passes_and_every_trigger_routes(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = SC.main(["--all", "--base", "HEAD"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertNotIn("ranks #", out.getvalue())          # every "should" is the top pick
        self.assertIn("0 newly wrong", out.getvalue())

    def test_every_skill_has_three_and_two_triggers(self):
        data = json.loads((ROOT / "evals" / "skill_triggers.json").read_text())
        names = {p.parent.name for p in list(ROOT.glob("skills/*/SKILL.md")) + list(ROOT.glob("packs/*/skills/*/SKILL.md"))}
        self.assertEqual(set(data) - {"note"}, names)
        for n in names:
            self.assertGreaterEqual(len(data[n]["should"]), 3, n)
            self.assertGreaterEqual(len(data[n]["should_not"]), 2, n)

    def test_triggers_are_not_copied_from_the_held_out_set(self):
        held = {t.lower() for t, _ in json.loads((ROOT / "evals" / "routing_cases.json").read_text())["held_out"]}
        data = json.loads((ROOT / "evals" / "skill_triggers.json").read_text())
        mine = {q.lower() for k, v in data.items() if k != "note" for q in v["should"] + v["should_not"]}
        self.assertEqual(mine & held, set())


class Regression(unittest.TestCase):
    """Deleting trigger words from a description must show up as cases newly wrong."""

    def test_detects_cases_lost_to_a_description_edit(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(ROOT / "skills", d / "skills")
        shutil.copytree(ROOT / "packs", d / "packs")
        md = d / "skills" / "ship" / "SKILL.md"
        text = md.read_text()
        desc = re.search(r"^description:\s*(.+)$", text, re.M).group(1)
        md.write_text(text.replace(desc, "Use when shipping."))
        cases = json.loads((ROOT / "evals" / "routing_cases.json").read_text())["dev"]
        before, after = SC.route(ROOT, cases), SC.route(d, cases)
        lost = [b[0] for b, a in zip(before, after) if b[4] and not a[4]]
        self.assertTrue(lost, "gutting ship's description lost no routing case: the guard is blind")


class Description(unittest.TestCase):
    def test_does_sentence_and_first_person(self):
        self.assertTrue(SC.DOES.match("Runs the quality gate."))
        self.assertTrue(SC.DOES.match("Fetches logs from CloudWatch."))
        self.assertFalse(SC.DOES.match("Use when the logs are in CloudWatch."))
        self.assertTrue(SC.FIRST_PERSON.search("I can help when tests are flaky"))
        self.assertFalse(SC.FIRST_PERSON.search("Use when an Item index is slow"))

    def test_agent_tool_names(self):
        self.assertTrue(SC.TOOL_NAMES.search("Use the Bash tool to run tests"))
        self.assertTrue(SC.TOOL_NAMES.search("call TodoWrite"))
        self.assertFalse(SC.TOOL_NAMES.search("run the tests and read the output"))


if __name__ == "__main__":
    unittest.main()
