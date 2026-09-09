# EST SPEC v1.0 — FROZEN 2026-09-07 before any run. Do not edit after runs start; amendments go in SPEC_AMENDMENTS.md with date.

## Construct
Participant AI-use proficiency ("elicitation skill"): ability to extract a fixed hidden set of
situation-specific facts from a conversational assistant under a turn/time budget and carry
them into a submitted answer. Items are benign and instance-specific (fictional lab / trek /
brewery records) so the base model cannot know the facts; only the controller can release them.

## Item structure (each item)
7 components C1..C7 + 1 correction component CFIX.
- C1: tier T0 (in assistant context from turn 1; assistant instructed to volunteer it).
- C2: tier T0, contains ONE planted internal inconsistency (arithmetic/date/time).
- C3, C4: tier T1 — unlocked when a participant turn addresses the component's topic at level
  >= general.
- C5, C6: tier T2 — unlocked only when a turn asks at level == specific (explicitly requests the
  concrete record / measurement / number / log named in `specific_requirement`). A general ask
  marks the component "raised" but does not unlock it.
- C7: tier T3 — two-strike: first qualifying ask (general or specific) -> strike 1, nothing
  released (assistant genuinely lacks it); second qualifying ask on a LATER turn -> unlocked.
- CFIX: released when a turn challenges/points out the inconsistency in C2.
The assistant only ever sees unlocked component text. It is never asked to withhold anything.

## Per-turn judge (controller)
Input: item topic map, conversation so far, latest participant message.
Output JSON: {levels: {C3..C7: none|general|specific}, challenges_error: bool}.
Logged verbatim per turn. This log IS the ground truth for raised/unlocked; no re-judging.

## Submission judge (scorer)
Input: submission text + text of every component. Output JSON: {present: [component ids],
flags_inconsistency: bool}. "present" = the submission conveys the substantive content of
that component (paraphrase counts; topic mention without the specific fact does not).

## Subscales (each in [0,1])
coverage          = |{c in C3..C7 : max level over turns >= general}| / 5
specificity       = |{c in {C5,C6} : unlocked}| / 2
refusal_recovery  = 1 if C7 unlocked else 0
verification      = 1 if (any turn challenges_error) or (submission flags_inconsistency) else 0
uptake            = |present ∩ obtained| / |obtained|, obtained = {C1,C2} ∪ unlocked(C3..C7)
composite         = mean of the five

Note (2026-09-08 15:34, owner direction recorded verbatim 2026-09-08: "i think you overcomplicated this. can you simplify the
task/ tool?"): the trial composite above is unchanged and is what analyze_trial.py and every reference number use. The
transcript-scoring tool (rank_transcripts.py, page section 2, v1.5.0) adds a separate headline `overall` = mean of the
behaviours that could be observed in the session (persistence, verification, uptake are NA when the session gave no
opportunity) with the count observed shown beside it, keeps `composite` in its output as "trial composite", and scores
every session of a task against one pinned checklist (designer targets if supplied; else a user-supplied checklist; else
one written by the tool once per task, shown in the output and cached) instead of letting the judge write its own list
inside each call. Judge model default stays claude-sonnet-5 (the model behind every anchor and agreement check);
claude-opus-5 is selectable and puts scores on a different, un-anchored scale.

## Caps
Turn cap 12 participant turns; hosted mode also 5-minute wall clock from /start.
Synthetic policies: WEAK max 2 turns, MEDIUM max 6, STRONG max 10.

## Synthetic participants (LLM-driven, never shown hidden components)
WEAK:   asks one broad question restating the task, optionally one generic follow-up, then
        submits a short summary of what it was told.
MEDIUM: decomposes the problem into likely categories and asks one question per category;
        accepts whatever answer comes back (no follow-up on vague/absent answers); submits a
        structured summary.
STRONG: decomposes; for each category asks for concrete records/numbers/logs; if an answer is
        vague or says no record, re-asks once more pointedly on a later turn; cross-checks
        stated numbers/dates for consistency and queries discrepancies; final submission
        enumerates every specific fact learned plus any inconsistency found.

## Gates (pre-registered)
G1 ordering (synthetic grid: 3 policies x 3 items x 2 seeds):
   (a) composite: mean over seeds satisfies STRONG > MEDIUM > WEAK on EVERY item;
   (b) each subscale, mean over items x seeds: STRONG >= MEDIUM >= WEAK and STRONG > WEAK.
   Pass = (a) and (b). Partial results reported regardless.
G2 judge accuracy: independent blind labeller (verifier agent) labels, for >=10 transcripts,
   per component: raised (any turn >= general), asked_specific (any turn == specific),
   in_submission. Pooled binary F1 of pipeline outputs vs labels >= 0.90.
On gate failure: report as failed with outputs. Policies/prompts are NOT tuned post hoc to
pass; any change after first grid run is logged in SPEC_AMENDMENTS.md and both results kept.

## Models
Controller judge + assistant + submission judge: claude-sonnet-5. Synthetic participants:
claude-haiku-4-5-20251001. Backend: headless `claude -p` (OAuth) locally; Anthropic SDK when
a working key is configured (hosted). Temperature default; seeds vary via a nonce in the
participant system prompt (CLI backend has no seed control) — documented limitation.

(Amendments after freeze live in SPEC_AMENDMENTS.md; A4 was briefly appended here on 2026-09-08 and moved there the same day.)
