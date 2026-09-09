"""Build the control (anchor) transcript set used by rank_transcripts.py --controls and the page's section 2.
Anchors = established transcripts with reference scores, scored alongside a user's transcripts on every run so that
(1) the user sees fixed reference points on the same 0-1 scale and (2) judge drift is detectable.
  scripted: EST synthetic fixtures WEAK / MEDIUM / STRONG (runs_v3, seed 1) on pcr_lab and western_blot, whose
            ground truth comes from the server-side controller (which records were actually released / retried / caught),
            i.e. independent of any transcript judge;
  human:    two public RealHumanEval participants (Mozannar et al. 2024), one low and one high on the 2026-09-08
            trial_real run, three sessions each, with designer targets; reference = that run's transcript-judge scores.
Writes controls/anchors.jsonl, controls/tasks.yaml, controls/expected.json, controls/judge_cache/*.json (shipped packed as controls/judge_cache.json)."""
import json, pathlib, sys, time, shutil, yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from est.transcripts import judge_session, metrics, session_hash, SONNET
OUT = ROOT / "controls"; CACHE = OUT / "judge_cache"; CACHE.mkdir(exist_ok=True, parents=True)
MAP = {"refusal_recovery": "persistence"}
recs, tasks, expected = [], {}, {"version": "controls-v1", "built_at": time.strftime("%F %T"), "judge_model": SONNET, "persons": {}, "sessions": {}}

# scripted anchors (controller ground truth)
dt = yaml.safe_load(open(ROOT / "demo_trial_v2/tasks.yaml"))
for pol, label in [("WEAK", "scripted WEAK: one broad question, accepts the first answer"), ("MEDIUM", "scripted MEDIUM: one category per turn, never asks for records, never re-asks"), ("STRONG", "scripted STRONG: asks for concrete records, re-asks, checks arithmetic, itemised answer")]:
    pid = f"control:{pol.lower()}-scripted"; expected["persons"][pid] = {"kind": "scripted", "label": label, "ground_truth": {}, "sessions": []}
    for si, item in enumerate(["pcr_lab", "western_blot"]):
        r = json.load(open(ROOT / f"runs_v3/{item}__{pol}__s1.json")); tid = f"control:est:{item}"
        tasks[tid] = dt[f"est:{item}"]
        rec = {"participant_id": pid, "session_idx": si, "task_id": tid, "messages": [{"role": m["role"], "content": m["content"]} for m in r["messages"]], "submission": r.get("submission")}
        recs.append(rec)
        gt = {MAP.get(k, k): v for k, v in r["score"]["subscales"].items()}
        expected["sessions"][f"{pid}/{si}"] = {"task_id": tid, "source": f"runs_v3/{item}__{pol}__s1.json", "ground_truth_controller": gt}
        expected["persons"][pid]["sessions"].append(f"{pid}/{si}")
    g = [expected["sessions"][k]["ground_truth_controller"] for k in expected["persons"][pid]["sessions"]]
    expected["persons"][pid]["ground_truth"] = {k: round(sum(x[k] for x in g) / len(g), 3) for k in g[0]}

# human anchors (public RealHumanEval, reference = trial_real judge run)
# data/realhumaneval/trial_real/ is derived at build time from the public RealHumanEval release and is not shipped;
# the outputs (controls/anchors.jsonl, expected.json, judge_cache.json) are, so the app never needs this input.
rt = yaml.safe_load(open(ROOT / "data/realhumaneval/trial_real/tasks.yaml"))
rhe = [json.loads(l) for l in open(ROOT / "data/realhumaneval/trial_real/transcripts.jsonl")]
for src, label in [("p64", "public human, low: RealHumanEval participant p64 (3 coding-help sessions, composite 0.09 in the 2026-09-08 run)"), ("p82", "public human, high: RealHumanEval participant p82 (3 sessions, composite 0.68, rank 2 of 107)")]:
    pid = f"control:human-{'low' if src=='p64' else 'high'}-{src}"; expected["persons"][pid] = {"kind": "human", "label": label, "sessions": []}
    mine = sorted([r for r in rhe if r["participant_id"] == src], key=lambda r: r["session_idx"])[:3]
    for si, r in enumerate(mine):
        tid = f"control:rhe:{r['task_id']}"; tasks[tid] = rt[r["task_id"]]
        rec = {"participant_id": pid, "session_idx": si, "task_id": tid, "messages": r["messages"], "submission": r.get("submission")}
        recs.append(rec); expected["sessions"][f"{pid}/{si}"] = {"task_id": tid, "source": f"RealHumanEval {src} session {r['session_idx']} ({r['task_id']})"}
        expected["persons"][pid]["sessions"].append(f"{pid}/{si}")
        # reuse the trial_real judge cache when the hash matches (same task dict, same transcript)
        h = session_hash(rec, tasks[tid]); old = ROOT / "data/realhumaneval/trial_real/judge_cache" / f"{h}.json"
        if old.exists() and not (CACHE / f"{h}.json").exists(): shutil.copy(old, CACHE / f"{h}.json")

# reference judge scores (build time) for every anchor session
SUBS = ["coverage", "specificity", "persistence", "verification", "uptake", "composite"]
for rec in recs:
    t = tasks[rec["task_id"]]; j = judge_session(rec, t, CACHE); m = metrics(j, list(t["targets"].keys()))
    k = f"{rec['participant_id']}/{rec['session_idx']}"
    expected["sessions"][k]["judge_reference"] = {s: (None if m[s] != m[s] else round(m[s], 3)) for s in SUBS}
    expected["sessions"][k]["transcript_hash"] = session_hash(rec, t)
for pid, P in expected["persons"].items():
    rows = [expected["sessions"][k]["judge_reference"] for k in P["sessions"]]
    P["judge_reference"] = {s: (round(sum(r[s] for r in rows if r[s] is not None) / max(1, sum(r[s] is not None for r in rows)), 3) if any(r[s] is not None for r in rows) else None) for s in SUBS}
expected["n_sessions"] = len(recs); expected["n_chars"] = sum(len(m["content"]) for r in recs for m in r["messages"])
expected["tolerance_composite"] = 0.15
expected["note"] = ("Scripted anchors carry controller ground truth (which records the server actually released, whether the withheld record was re-asked, whether the planted error was challenged, which obtained records reached the answer), so judge-vs-truth on them is an objective check of the transcript judge. Human anchors are public RealHumanEval sessions; their reference is the transcript judge's own score on the 2026-09-08 run, so they check judge stability, not judge validity. "
                    "The EST subscale refusal_recovery is mapped to persistence; EST specificity (share of precise-question records unlocked) and transcript specificity (share of on-target turns that were specific) are related but not identical constructs, so expect agreement in ordering, not equality.")
with open(OUT / "anchors.jsonl", "w") as f:
    for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
yaml.safe_dump(tasks, open(OUT / "tasks.yaml", "w"), allow_unicode=True, width=120, sort_keys=False)
json.dump(expected, open(OUT / "expected.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps({p: {"gt": v.get("ground_truth", {}).get("composite"), "judge": v["judge_reference"]["composite"]} for p, v in expected["persons"].items()}, indent=1)); print(expected["n_sessions"], expected["n_chars"])
