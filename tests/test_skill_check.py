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


GOOD = """---
name: changelog-first
description: Use when about to merge, tag or release a change that users will notice, including small fixes and hotfixes.
---

# changelog-first

Every user-visible change gets a CHANGELOG entry before it is merged. See `references/why.md`.

## The rule

No entry, no merge. A hotfix is not an exception.

## Done when

The pull request carries the CHANGELOG entry.
"""
SIBLINGS = {
    "deploy": "Use when deploying the web app to staging or production, or rolling a release back.",
    "unit-tests": "Use when writing or fixing unit tests, or a test fails.",
}


class AnyFolder(unittest.TestCase):
    """Path mode: a skill anywhere, judged by the general rules, not the library's."""

    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        for n, desc in SIBLINGS.items():
            (self.d / n).mkdir()
            (self.d / n / "SKILL.md").write_text("---\nname: %s\ndescription: %s\n---\n\n# %s\n\n## Done when\n\nDone.\n" % (n, desc, n))
        self.skill = self.d / "changelog-first"
        (self.skill / "references").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text(GOOD)
        (self.skill / "references" / "why.md").write_text("# why\n\nUsers read it.\n")

    def run_check(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = SC.main([str(self.skill), *extra])
        return rc, out.getvalue()

    def edit(self, old, new, rel="SKILL.md"):
        p = self.skill / rel
        text = p.read_text()
        self.assertIn(old, text)
        p.write_text(text.replace(old, new))

    def triggers(self, should, should_not):
        p = self.d / "t.json"
        p.write_text(json.dumps({"should": should, "should_not": should_not}))
        return str(p)

    def test_good_skill_is_clean(self):
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("0 FAIL, 0 WARN", out)

    def test_each_defect_is_named(self):
        cases = [
            ("name: changelog-first", "name: Changelog_First", "FAIL", "must be lowercase letters"),
            ("name: changelog-first", "name: changelog", "WARN", "differs from its folder"),
            ("description: Use when about", "description: Notes: use when about", "FAIL", "': ' unquoted"),
            ("description: Use when about to merge,", "description: I help when you merge,", "WARN", "first person"),
            ("and hotfixes.", "and hotfixes. Writes the entry and opens the PR.", "WARN", "says what the skill does"),
            ("See `references/why.md`.", "See `references/how.md`.", "FAIL", "references/how.md, which does not exist"),
            ("No entry, no merge.", "No entry, <what happens>, no merge.", "FAIL", "placeholder left in"),
            ("## Done when", "## Finally", "WARN", "no 'Done when'"),
        ]
        for old, new, level, want in cases:
            self.skill.joinpath("SKILL.md").write_text(GOOD)
            self.edit(old, new)
            rc, out = self.run_check()
            self.assertTrue(any(l.startswith(level) and want in l for l in out.splitlines()), "%s:\n%s" % (want, out))

    def test_unlinked_reference_and_unnamed_script_warn(self):
        (self.skill / "references" / "extra.md").write_text("# extra\n")
        (self.skill / "scripts").mkdir()
        (self.skill / "scripts" / "lint.py").write_text("print(1)\n")
        rc, out = self.run_check()
        self.assertIn("references/extra.md", out)
        self.assertIn("scripts/lint.py", out)

    def test_code_examples_are_not_placeholders(self):
        self.edit("No entry, no merge.", "No entry, no merge.\n\n```text\n- <the change> (#<pr>)\n```")
        self.assertEqual(self.run_check()[0], 0)

    def test_long_body(self):
        self.edit("## Done when", "\n".join("line %d" % i for i in range(520)) + "\n## Done when")
        self.assertIn("move detail into references/", self.run_check()[1])

    def test_triggers_route_against_the_siblings(self):
        ok = self.triggers(["About to merge this hotfix", "Tag the 2.3.0 release", "Can I merge this small fix?"],
                           ["Deploy to staging", "This unit test fails"])
        rc, out = self.run_check("--triggers", ok)
        self.assertEqual(rc, 0, out)
        bad = self.triggers(["Roll the release back on production", "Tag the 2.3.0 release", "Merge this hotfix"],
                            ["Merge the hotfix now", "This unit test fails"])
        rc, out = self.run_check("--triggers", bad)
        self.assertEqual(rc, 1)
        self.assertIn("should reach it, routes to deploy", out)
        self.assertIn("should not reach it, but does: Merge the hotfix now", out)

    def test_alone_in_its_folder_says_so(self):
        lone = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, lone, True)
        shutil.copytree(self.skill, lone / "changelog-first")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            SC.main([str(lone / "changelog-first"), "--triggers", self.triggers(["merge"], ["deploy"])])
        self.assertIn("no other skills beside it", out.getvalue())


class Scaffold(unittest.TestCase):
    def test_each_type_fails_until_filled(self):
        for kind in sorted(SC.SCAFFOLD):
            d = pathlib.Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, d, True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(SC.main(["new", "my-skill", "--type", kind, "--dir", str(d)]), 0)
                rc = SC.main([str(d / "my-skill")])
            self.assertEqual(rc, 1, kind)                   # slots are placeholders until filled
            self.assertTrue((d / "my-skill" / "triggers.json").exists())

    def test_refuses_a_bad_name_or_an_existing_folder(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(SC.main(["new", "Bad_Name", "--type", "technique", "--dir", str(d)]), 2)
            SC.main(["new", "ok", "--type", "technique", "--dir", str(d)])
            self.assertEqual(SC.main(["new", "ok", "--type", "technique", "--dir", str(d)]), 2)
