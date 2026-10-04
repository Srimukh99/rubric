# write

A skill is a small document an agent loads by its description and then follows
with no one watching. Write it for that reader: busy, literal, and inclined to
take the shortest path the text allows.

## 1. Decide what it is

| It is… | So it becomes… |
| --- | --- |
| A rule a script or regex can check | A script or hook. Prose for it is a wish |
| A fact about one project (its commands, paths, conventions) | A line in that project's `AGENTS.md` / `CLAUDE.md` |
| A one-off story of how something got solved | Nothing. A skill is reusable or it is noise |
| A technique, rule or reference you would want again across projects | A skill |

## 2. Know its type: each is written and tested differently

| Type | It… | Write it as | Prove it by |
| --- | --- | --- | --- |
| **Discipline** | makes the agent do something it knows it should, under pressure (test first, proof before "done") | the rule, the phrases that signal the skip, an excuse → reality table, and a script for what can be enforced | pressure tasks where skipping is tempting |
| **Technique** | teaches a how-to (trace a bad value back, wait on a condition) | numbered steps with one worked example in the user's domain | a new task where the technique must be applied |
| **Pattern** | gives a way of seeing a problem (one purpose per unit) | the idea, a recognition test, one example, one counter-example | tasks where it should apply and tasks where it should not |
| **Reference** | holds facts to look up (an API, a flag set) | tables and short entries, findable by the word someone would search | lookup tasks, including one the reference does not cover |

## 3. The description decides whether it is ever read

It sits in every session's context; the agent reads it to choose. So it is a
condition, not a summary.

| Weak | Why | Strong |
| --- | --- | --- |
| `Helps with tests.` | No condition, no words anyone types | `Use when a test passes alone but fails in the full suite, or fails only sometimes.` |
| `I can review your Terraform.` | First person; reads as a voice, not a rule | `Use when writing or reviewing Terraform, CloudFormation or Helm, or asked if infrastructure is secure.` |
| `Use when deploying: build, push, migrate, then watch dashboards.` | Summarises the steps; an agent can act on the summary and never open the skill | `Use when deploying to staging or production, or rolling a release back.` |
| `Use when setTimeout makes tests flaky.` | Names one symptom of a general problem | `Use when tests depend on timing, race, or hang under load.` |

- Start with "Use when"; third person; about 40 words at most.
- Use the words people actually type: error text, symptoms, tool and product
  names, and the two or three synonyms they reach for.
- Name a technology only when the skill is specific to it.
- If a trigger word carries meaning, keep it, as a condition. Cutting a
  sentence can cost the words the router matched on: measure (step 7).

## 4. Shape the body

- One line on what it is for, then the steps. Imperative: "run", "write", "stop".
- Headings an agent can jump to; tables over paragraphs for anything with
  rows; one example, complete and in a real domain, not three thin ones.
- End with **Done when**: the observable state that means the job is finished.
- Keep the always-read part short (aim under 150 lines). Long material goes
  in a `references/` file the skill points at, so it is read only when needed;
  a deterministic helper goes in `scripts/`, named in the text so it is found.
- Say what to do, not which agent tool to press, unless the skill is for one
  agent only.

```text
my-skill/
  SKILL.md            description + steps or a table pointing at references
  references/*.md     one job each, read on demand
  scripts/*           checks the text would otherwise ask the model to remember
```

## 5. Match the form to the failure you saw

Watch the failure first (`references/test.md`), then pick the form:

| The agent… | The fix is… | Not… |
| --- | --- | --- |
| skipped a rule it knew, when pressed | the rule stated flatly, the tell-tale phrases, an excuse → reality table | softer advice ("try to…") |
| produced the right content in the wrong shape | a template with fixed slots, in order | a list of things to remember |
| left out a required part | a required field the template cannot be filled without, plus a check | a reminder near the end |
| acted when it should not, or not when it should | a condition it can observe ("when the plan has a `Design:` line") | a rule plus exceptions |

## 6. Close the loopholes you saw

For a discipline skill, every excuse a tested agent gave becomes a row:

```text
| "It's a one-line change" | One-line changes break builds. The check takes seconds |
```

- Forbid the specific workaround, not just the outcome: "do not keep the
  untested code as a reference" closes a door "write the test first" leaves open.
- No "unless it matters" or "where appropriate": each reopens the argument.
- One sentence early covers the rest: rewording a forbidden step does not make
  it allowed.

## 7. Check it

`python3 <this skill folder>/scripts/skill_check.py PATH/TO/SKILL` FAILs on:

- a description in the first person, one that carries a workflow ("... -
  dispatches a subagent per task"), or a sentence saying what the skill does;
- a clause that reopens a rule ("don't skip it unless it matters");
- a hard rule (a "The rule" heading, MUST or NEVER, "no exceptions") with no
  excuse table, no red flags, or no recorded baseline;
- a link to a file that is not there, a placeholder left in.

It WARNs on length, a missing **Done when**, a reference or script nothing
points at, and a soft condition in a step ("if needed"). With
`--triggers FILE` it routes prompts that should and should not reach the
skill against the others in the same folder: the top pick, or FAIL. Then
`references/test.md` for behaviour.

## Done when

The description is a condition in the words people type, the body matches the
skill's type and the failure observed, `skill_check.py` is clean, and the
behaviour test in `references/test.md` passed or is reported as not run.
