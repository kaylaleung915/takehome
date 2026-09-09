# Elicitation Skill Test (EST)

A research prototype for Theme 4 (Evaluation and Data Quality). The evaluations that set chemical, biological and cyber capability thresholds in model system cards are human-uplift trials: one group works with the model, another without, and the difference in graded output is the uplift. They grade the outcome carefully and do not record how well each participant got information out of the model; in the one trial with public per-person data (OpenAI 2024), 4 of 50 participants given the model never messaged it and 20 percent of task responses were written with zero messages. Two trials can therefore run the same model on the same tasks and report different uplift because their participants asked differently, and neither report contains the number needed to tell. That unrecorded variance is the data-quality problem EST addresses, with two tools:

1. A transcript scorer: an LLM-as-judge pipeline that reads the chat logs from a trial's model arm and scores five elicitation behaviours per session. The judge labels individual turns against a pinned task checklist rather than assigning a grade, the arithmetic is fixed in code, 12 control sessions with known scores are re-scored alongside every upload so the scale is anchored, the judge passed a pre-registered agreement check (F1 0.96 against an independent blind labeller), and every result returns the judge output, the checklist used and the content-hash cache key. A `--controls-fresh` mode re-judges the controls to detect judge or backend drift.
2. A 20-minute, non-hazardous, automatically scored level that measures the same five behaviours before randomisation, so the score can be used as a baseline covariate or stratifier. Here the tool wrote the scenario and logs what the assistant releases, so four of the five behaviours need no judge at all.

The mechanics have been shown to separate scripted participants; nothing here has been validated on people. `DESIGN.md` says why that matters and what a pilot would need to show.

## Try it

Deployed prototype: https://anthropic-stem-fellows-kaylal--est-demo-web.modal.run

The page works without an account or key. Section 1 is a playable level (hosted mode uses the server's credential). Section 2 scores transcripts; press "Load sample transcripts" for six bundled sessions from three simulated participants (LLM-played personas named sim-weak, sim-medium and sim-strong), then "Score transcripts". The sample result replays from a shipped judge cache, so it returns in a few seconds and needs no new model calls. Ticking "Also score 12 control sessions with known scores" adds the scripted WEAK, MEDIUM and STRONG participants and one low and one high participant from RealHumanEval (a public dataset of people coding with an LLM), re-scored in the same request, so uploaded sessions can be read against fixed points; the results table shows each control session's expected score (logged by the level itself for the scripted three, the judge's build-time score for the RealHumanEval two) next to its score in this run. The sim personas and the scripted controls are two separately built families whose labels are not calibrated to each other, so a sim persona can score above or below the control of the same name.

## Run locally

Python 3.12 or later (the deployed image uses 3.12):

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # or CLAUDE_CODE_OAUTH_TOKEN for the headless claude CLI backend
.venv/bin/uvicorn app.server:app --port 8000
```

Open http://localhost:8000. Without a credential the page still serves the precomputed results, the sample-transcript demo (cache hit) and bring-your-own-key mode for section 1.

Command-line scoring of a transcript file, any size (the bundled sample works as a first input):

```
.venv/bin/python rank_transcripts.py app/static/samples/simulated_trial_6sessions.jsonl \
    --checklist app/static/samples/simulated_trial_checklist.json --controls --out out/
```

For a real trial, pass `--tasks tasks.yaml` (schema in `trial/SCHEMA.md`) so each task is scored against the trial designer's own checklist.

Post-trial analysis with pre-test scores, transcripts and model-alone ceiling scores (schema in `trial/SCHEMA.md`, worked example in `demo_trial_v2/`, output in `demo_trial_v2/results/`):

```
.venv/bin/python analyze_trial.py --trial-dir demo_trial_v2
```

## Deploy

```
modal deploy -e <environment> app/modal_app.py
```

The app expects a Modal secret named `anthropic-est` holding one of the two credentials above. Session records persist on the volume `est-demo-runs`.

## How scoring works

The five behaviours (coverage, specificity, persistence, verification, uptake) are this project's translation of what the uplift-trial literature describes qualitatively as weak use: one broad question, accepting a deflection, not checking the model, not using what it gave. The sources name the problem but define no constructs; `DESIGN.md` section 1 gives the provenance. Each score is a share between 0 and 1, or 1/0 for did or did not (persistence and verification in a level, verification in a transcript), and the level and the transcript scorer use the same definitions (section 3 of the web page).

Each level hides seven records behind a cooperative assistant with graded release rules (two volunteered, two on raising the topic, two on a request for the specific record, one withheld until asked a second time; one volunteered record carries a planted inconsistency), and the level logs each release, so four scores are counted from that log and an LLM judge only checks which obtained records appear in the written answer (uptake). A transcript from a real trial has no such log, so one judge call per session labels each participant turn against a task checklist (what it asks about, whether the ask is concrete, whether it re-asks after a non-answer (a reply that declines, deflects or says nothing was found), whether it checks the assistant), and the same formulas, fixed in code, turn the labels into scores. A behaviour that could not be observed is NA rather than 0 (persistence with no non-answer, uptake with no separate written answer), and the overall score is the mean of the behaviours observed. Details in `DESIGN.md` section 2.

Two pass/fail checks (G1, G2) were frozen in `SPEC.md` before any run, and the failed runs are kept. G1 requires the scripted STRONG participant to beat MEDIUM and MEDIUM to beat WEAK on every level (`results/g1_run3/`). G2 requires the answer judge to reach an F1 (harmonic mean of precision and recall) of at least 0.90 against an independent blind labeller (F1 0.96 on 126 labels, `app/static/precomputed.json`). Passing shows that the mechanics separate scripted behaviour; it says nothing about human validity.

## Layout

| Path | Contents |
|---|---|
| `app/` | FastAPI server, transcript-scoring API, Modal deployment, static page, bundled samples and their judge cache |
| `est/` | Level controller, scorer, transcript judge, LLM backends, estimands |
| `items/` | The three levels (benign lab-troubleshooting scenarios) with their hidden records |
| `controls/` | The 12 control sessions, their expected scores and cached judge outputs |
| `rank_transcripts.py` | Command-line transcript scorer |
| `analyze_trial.py` | Post-trial pipeline: stratified uplift estimates, elicitation ratio (participant score over the model-alone ceiling on the same task) |
| `trial/SCHEMA.md` | What a trial must record for the pipeline to run |
| `demo_trial_v2/` | Inputs and report of a simulated 48-participant trial used to exercise the pipeline end to end |
| `results/` | Synthetic baselines and gate results read by the page, and the G1 run 3 report |
| `SPEC.md`, `SPEC_AMENDMENTS.md` | Frozen design and dated amendments |
| `DESIGN.md` | Design rationale for the submission |
| `docs/RESEARCH_NOTES.md` | Long-form research notes (audit of published uplift trials, reliability analyses on public human chat data). They cite verifier reports, raw data pulls, run logs, tests and build scripts that are not shipped; the numbers they support are restated inline |

This repository holds what the deployed prototype runs on, the two submission documents and the files those documents cite. Build-time scripts (the scripted participants, the control and static-page builders, the simulated-trial generators), the test suite and the supporting evidence reports were left out to keep it small.

## Data handling

The transcript scorer sends transcript text to the model API. Do not point the hosted page at transcripts from sensitive trials (chemical, biological, cyber); run `rank_transcripts.py` or `analyze_trial.py` where those transcripts live.
