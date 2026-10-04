# weigh-in

Review feedback is a claim to check, not an instruction to obey and not an
attack to answer.

## Before changing anything

1. Read every comment first. Items are often related; fixing three of five
   and asking about two is how a half-understood change lands.
2. Restate each in one line. Any you cannot restate, ask about now, by
   number, before touching code.
3. Check each against the code, the tests, the plan and earlier decisions by
   the user:
   - **Correct**: fix it, with a test where behaviour changes.
   - **Wrong for this code**: reply with evidence (a test, a line, a doc).
     Wrong includes: breaks existing behaviour, misses context, conflicts with
     a decision the user made, or does not fit this stack or version.
   - **Unverifiable here**: say what you would need to check it.
   - **Out of scope**: log it as a follow-up.
   - **"Do it properly"**: search for real callers first. Building out
     something nothing uses is not "properly", it is more to maintain.
4. A comment that conflicts with the user's earlier decision goes to the
   user, not into the code.

## Applying

Blockers and security first, then small fixes, then the larger ones. One
change at a time, with its tests run after each. Re-run
`review_pack.py` over the fix range before asking for a re-review.

## Replying

State what changed and where, or the evidence for not changing it. No
performed agreement or thanks: the fix is the acknowledgement. If you pushed
back and were wrong, say so in one line and fix it.

Finish with a table: comment, decision, what changed or why not.
