"""Script-adherence stats for the v3 (state-machine) fixtures, computed from runs_v3/*.json `fixture_plan`.
Usage: .venv/bin/python results/g1_run3/adherence_check.py  -> writes results/g1_run3/adherence.json and prints markdown."""
import json, pathlib, sys, statistics as st
ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs_v3"
out = {"STRONG": {}, "MEDIUM": {}, "WEAK": {}, "per_item_composite": {}, "llm_calls": {}}
recs = [json.load(open(p)) for p in sorted(RUNS.glob("*.json"))]
calls = 0
for r in recs:
    rid = f"{r['item_id']}__{r['policy']}__s{r['seed']}"
    calls += r.get("n_llm_calls") or 0
    fp = r["fixture_plan"]; turns = fp["turns"]; log = r["log"]
    if r["policy"] == "STRONG":
        cats = fp["categories"]
        # (a) every category the checker marked unanswered after its first ask got a later ask (REASK or named in SWEEP)
        needed, reasked, detail = 0, 0, []
        for c in cats:
            if not c["asks"]:
                detail.append({"category": c["name"], "status": "never asked"}); continue
            first = c["asks"][0]
            tr = next((t for t in turns if t["turn"] == first), None)
            ck = (tr or {}).get("checker", {})
            ans = ck.get("answered", {}).get(c["name"])
            if ans is None and ck.get("answered"):
                # fall back to positional mapping like the fixture does
                asked = ck.get("asked", []); vals = list(ck["answered"].values())
                if c["name"] in asked and asked.index(c["name"]) < len(vals): ans = vals[asked.index(c["name"])]
            unanswered = not (bool(ans) and ans not in ("false", "False", 0))
            if first >= fp["max_turns"]:
                detail.append({"category": c["name"], "first_ask": first, "status": "first asked on final turn (n/a)"}); continue
            if unanswered:
                needed += 1
                later = [a for a in c["asks"] if a > first]
                ok = bool(later); reasked += ok
                detail.append({"category": c["name"], "first_ask": first, "unanswered_after_first": True, "later_asks": later, "re_asked": ok})
            else:
                detail.append({"category": c["name"], "first_ask": first, "unanswered_after_first": False, "later_asks": [a for a in c["asks"] if a > first]})
        other = next((c for c in cats if c.get("is_other")), None)
        other_asks = other["asks"] if other else []
        # judge outcome on the other-reports turns (informational; uses controller log, not available to the fixture)
        c7_on_other_turns = {t: next((l["judge"]["levels"].get("C7") for l in log if l["turn"] == t), None) for t in other_asks}
        # (c) challenge when checker flagged
        flagged_turns = [t["turn"] for t in turns if (t.get("checker") or {}).get("inconsistencies")]
        challenge_turns = [t["turn"] for t in turns for a in t["actions"] if a["type"] == "CHALLENGE"]
        first_flag = flagged_turns[0] if flagged_turns else None
        challenged_after_flag = (first_flag is not None and any(ct > first_flag for ct in challenge_turns))
        judge_credit = {ct: next((l["judge"]["challenges_error"] for l in log if l["turn"] == ct), None) for ct in challenge_turns}
        n_first_asked = sum(1 for c in cats if c["asks"])
        out["STRONG"][rid] = {
            "n_categories": len(cats), "n_categories_asked_at_least_once": n_first_asked,
            "reask_needed": needed, "reask_done": reasked, "reasked_every_unanswered": needed == reasked,
            "other_reports_asks": other_asks, "other_reports_asks_ge2": len(other_asks) >= 2, "judge_C7_level_on_those_turns": c7_on_other_turns,
            "checker_flagged_turns": flagged_turns, "challenge_turns": challenge_turns,
            "challenged_after_checker_flag": (None if first_flag is None else challenged_after_flag), "judge_challenges_error_on_challenge_turns": judge_credit,
            "message_sources": [t["message_source"] for t in turns], "n_turns": r["n_turns"],
            "subscales": r["score"]["subscales"], "unlocked": r["unlocked"], "detail": detail,
        }
    elif r["policy"] == "MEDIUM":
        srcs = [t["message_source"] for t in turns]
        asks_per_cat = [len(c["asks"]) for c in fp["categories"]]
        out["MEDIUM"][rid] = {"categories": [c["name"] for c in fp["categories"]], "asks_per_category": asks_per_cat,
                              "never_reasked": all(a <= 1 for a in asks_per_cat), "n_turns": r["n_turns"], "message_sources": srcs,
                              "any_challenge_judged": any(l["judge"]["challenges_error"] for l in log), "subscales": r["score"]["subscales"]}
    else:
        out["WEAK"][rid] = {"n_turns": r["n_turns"], "message_sources": [t["message_source"] for t in turns],
                            "judge_levels": [l["judge"]["levels"] for l in log], "subscales": r["score"]["subscales"]}
by = {}
for r in recs:
    by.setdefault(r["item_id"], {}).setdefault(r["policy"], []).append(r["score"]["subscales"]["composite"])
out["per_item_composite"] = {i: {p: round(st.mean(v), 4) for p, v in d.items()} for i, d in by.items()}
out["llm_calls"] = {"sum_n_llm_calls_over_runs": calls, "n_runs": len(recs),
                    "sum_wall_s_over_runs": round(sum(r.get("wall_s") or 0 for r in recs), 1)}
json.dump(out, open(ROOT / "results/g1_run3/adherence.json", "w"), indent=1)
S = out["STRONG"]
print("| STRONG run | cats asked/total | re-ask needed | re-ask done | all re-asked | other-reports asks | >=2 | checker flagged (turns) | challenge turns | challenged after flag | judge credited | composite |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for rid, d in S.items():
    print(f"| {rid} | {d['n_categories_asked_at_least_once']}/{d['n_categories']} | {d['reask_needed']} | {d['reask_done']} | {d['reasked_every_unanswered']} | {d['other_reports_asks']} | {d['other_reports_asks_ge2']} | {d['checker_flagged_turns']} | {d['challenge_turns']} | {d['challenged_after_checker_flag']} | {d['judge_challenges_error_on_challenge_turns']} | {d['subscales']['composite']:.2f} |")
print()
print("MEDIUM never re-asked:", {k: v["never_reasked"] for k, v in out["MEDIUM"].items()})
print("MEDIUM message sources:", {k: v["message_sources"] for k, v in out["MEDIUM"].items()})
print("WEAK turns:", {k: v["n_turns"] for k, v in out["WEAK"].items()})
print("per-item composite:", out["per_item_composite"])
print("llm calls:", out["llm_calls"])
