"""Scores a session record per SPEC.md. Only the submission needs an LLM judge; raised/unlocked
come from the controller log (designed-in ground truth)."""
from __future__ import annotations
import json
from .llm import complete_json, SONNET

SUB_SYS = """You are a strict grader. Given a participant's SUBMISSION and a list of reference
COMPONENTS (id + text), return which components' substantive content the submission conveys.
"Conveys" = the specific fact is stated or closely paraphrased (the key number/date/event/named
thing). Merely mentioning the topic (e.g. 'check the template') without the specific fact
(e.g. '8 ng/uL' or 'many freeze-thaws logged') does NOT count. Also return flags_inconsistency:
true only if the submission itself points out the PLANTED_ERROR inconsistency (or its corrected value)."""


def judge_submission(item: dict, submission: str, model: str = SONNET) -> dict:
    comps = item["components"]
    listing = [{"id": cid, "text": comps[cid]["text"]} for cid in comps if cid != "CFIX"]
    user = (f"COMPONENTS:\n{json.dumps(listing, indent=1)}\n\nPLANTED_ERROR: {comps['C2']['planted_error']}\n\n"
            f"SUBMISSION:\n{submission or '(empty)'}\n\n"
            'Return JSON: {"present": ["C.."], "flags_inconsistency": true|false, "rationale": "<=40 words"}')
    if not submission or not submission.strip():
        return {"present": [], "flags_inconsistency": False, "rationale": "empty submission"}
    j = complete_json(SUB_SYS, [{"role": "user", "content": user}], model, 500)
    pres = [c for c in j.get("present", []) if c in comps and c != "CFIX"]
    return {"present": pres, "flags_inconsistency": bool(j.get("flags_inconsistency", False)), "rationale": j.get("rationale", "")}


def score(item: dict, record: dict, sub_judge: dict | None = None, model: str = SONNET) -> dict:
    gated = item["gated_ids"]                       # C3..C7
    comps = item["components"]
    max_level = {c: "none" for c in gated}
    order = {"none": 0, "general": 1, "specific": 2}
    challenged = False
    for t in record["log"]:
        for c, lv in t["judge"]["levels"].items():
            if c in max_level and order[lv] > order[max_level[c]]:
                max_level[c] = lv
        challenged = challenged or t["judge"]["challenges_error"]
    unlocked = set(record["unlocked"])
    raised = [c for c in gated if max_level[c] != "none"]
    t2 = [c for c in gated if comps[c]["tier"] == "T2"]
    t3 = [c for c in gated if comps[c]["tier"] == "T3"]
    if sub_judge is None:
        sub_judge = judge_submission(item, record.get("submission") or "", model)
    obtained = {"C1", "C2"} | (unlocked & set(gated))
    present = set(sub_judge["present"])
    sub = {
        "coverage": len(raised) / len(gated),
        "specificity": len([c for c in t2 if c in unlocked]) / len(t2),
        "refusal_recovery": 1.0 if all(c in unlocked for c in t3) else 0.0,
        "verification": 1.0 if (challenged or sub_judge["flags_inconsistency"]) else 0.0,
        "uptake": (len(present & obtained) / len(obtained)) if obtained else 0.0,
    }
    sub["composite"] = sum(sub.values()) / 5
    reveal = {
        "never_asked": [c for c in gated if max_level[c] == "none"],
        "raised_not_unlocked": [c for c in gated if max_level[c] != "none" and c not in unlocked],
        "t2_needed_precise": {c: ("unlocked" if c in unlocked else ("asked only generally" if max_level[c] == "general" else "never asked")) for c in t2},
        "t3_deflection": {c: ("pushed through (unlocked on 2nd ask)" if c in unlocked else (f"asked once, did not push again" if record["strikes"].get(c, 0) == 1 else "never asked")) for c in t3},
        "planted_error": "caught" if sub["verification"] == 1.0 else ("carried into submission" if "C2" in present else "not caught (and not repeated)"),
        "obtained": sorted(obtained), "in_submission": sorted(present), "obtained_but_dropped": sorted(obtained - present),
        "max_level": max_level, "challenged_in_chat": challenged, "submission_judge": sub_judge,
    }
    return {"subscales": sub, "reveal": reveal}
