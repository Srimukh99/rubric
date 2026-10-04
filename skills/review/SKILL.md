---
name: review
description: Use when a finished task needs an independent review of the diff before merging, when review comments arrive and need judging on merit, or when code touches login, sessions, permissions, secrets, uploads, webhooks or personal data.
---

# review

Read only the part you need.

| Situation | Read |
| --- | --- |
| Code touches login, sessions, permissions, secrets, file uploads, user input parsing, outbound calls, webhooks or personal data. Reviews the change for security flaws before it ships. | `references/threat-check.md` |
| A task or feature is finished and before merging or opening a PR. Settles the facts by script, then gets an independent review of what is left, ranked by severity with a verdict. | `references/second-look.md` |
| You receive code review comments or suggestions, from a person or an agent, before changing any code. Judges each point on its merits instead of agreeing by reflex. | `references/weigh-in.md` |

Order: `references/threat-check.md` while writing security-sensitive code, `references/second-look.md` when the change is finished, `references/weigh-in.md` when comments come back.

Script: `scripts/review_pack.py` (one file for the reviewer: the plan checked against the code, the gates run, then the diff).
