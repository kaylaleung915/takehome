"""Bundles precomputed results + (base64-obfuscated) items + prompt texts into app/static/precomputed.json
so the page works with no server (BYOK / offline panels). Re-run after results change."""
import json, base64, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from est.items import load_item, list_items, public_view
from est.controller import JUDGE_SYS
from est.scorer import SUB_SYS
from est.llm import SONNET
R = ROOT / "results"
def rd(n, js=False):
    p = R / n
    if not p.exists(): return None
    return json.load(open(p)) if js else p.read_text()
def human_summary():
    """Compact, number-only summary of the non-synthetic layers for the page (full reports stay in results/)."""
    H = {}
    prj = rd("published_ratios.json", True)
    if prj:
        H["ratios"] = [{"study": r["study"], "domain": r.get("domain", "")[:80], "human_llm": r.get("human_llm", ""), "ceiling": (r.get("ceiling") or [{}])[0].get("value", ""),
                        "R_cap": r.get("R_cap"), "R_hum": r.get("R_hum"), "hi_conf": bool(r.get("confidence_ge_90")), "cross_variant": bool(r.get("cross_variant"))} for r in prj["rows"]]
        H["ratios_noncomputable_n"] = len(prj.get("non_computable", [])); H["ratios_verifier"] = (prj.get("verification") or {}).get("report")
    pj = rd("prism_report.json", True)
    if pj:
        L1 = pj["q1_layer1"]; ms = L1["measures"]
        H["prism"] = {"n_persons": L1["n_persons"], "n_conversations": L1["n_conversations"],
                      "rho_fam": {k: {"rho": round(v["spearman_familiarity"]["rho"], 3), "lo": round(v["spearman_familiarity"]["lo"], 3), "hi": round(v["spearman_familiarity"]["hi"], 3),
                                      "delta_r2": round(v["ols_familiarity"]["delta_r2"], 4), "person_r2": round(v["person_r2_familiarity"], 4) if isinstance(v.get("person_r2_familiarity"), (int, float)) else None} for k, v in ms.items()},
                      "split_half": {k: {"rho": round(v["pooled"]["split_half"]["rho"], 3), "icc1": round(v["pooled"]["icc"]["icc1"], 3), "icc1k": round(v["pooled"]["icc"]["icc1k"], 3), "icc1_lo": round(v["pooled"]["icc"]["icc1_lo"], 3), "icc1_hi": round(v["pooled"]["icc"]["icc1_hi"], 3)} for k, v in pj["q2_layer1"]["measures"].items()},
                      "layer2_n": (pj.get("q1_layer2") or {}).get("n_persons")}
    rj = rd("realhumaneval_report.json", True)
    if rj:
        H["rhe"] = {"n": rj["n"], "base_rates": {k: {"mean": v["episode_mean"], "ci": v["ci95_cluster_boot"], "n": v["n_episodes_defined"]} for k, v in rj["A_base_rates"].items()},
                    "audit": rj["A_under_elicitation_audit"], "rank": {k: {"split_half": v["split_half_spearman"], "ci": v["spearman_ci95_boot"], "icc1": v["icc1"]} for k, v in rj["B_rank_stability"].items() if isinstance(v, dict) and "icc1" in v},
                    "selfreport": {k: {"rho": v["spearman"], "r2": v["r2_linear"], "eta2": v["r2_categorical_eta2"]} for k, v in rj["C_self_report"].get("ai_exp_ord_vs", {}).items()}}
    return H
png = R / "openai2024.png"
out = {
  "items_public": [public_view(load_item(i)) for i in list_items()],
  "prompts": {"judge_sys": JUDGE_SYS, "sub_sys": SUB_SYS, "model": SONNET},
  # G1 run 3 (state-machine fixtures, SPEC_AMENDMENTS A2) is shown on the page when present; runs 1-2 (LLM-scripted fixtures, both
  # G1 FAIL) stay in results/table.md + baselines.json and are summarised in g1_history so the page never hides the failures.
  "baselines": rd("g1_run3/baselines.json", True) or rd("baselines.json", True),
  "table_md": rd("g1_run3/table.md") or rd("table.md"),
  "baselines_run2": rd("baselines.json", True), "table_md_run2": rd("table.md"),
  "g1_history": "G1 run 1 (items v1, LLM-scripted fixtures): FAIL at pooled uptake MEDIUM 0.739 < WEAK 0.750 (verification/V1_numbers.md). Run 2 (items v2, LLM-scripted fixtures): FAIL at pooled specificity STRONG 0.50 < MEDIUM 0.67 and STRONG refusal_recovery 0.50 (verification/V1c_numbers_v2grid.md). Run 3 (items v2, state-machine fixtures est/participants_v2.py, gates/scorer/controller unchanged): PASS, STRONG at ceiling, two non-blind pre-flight fixture edits disclosed, n = 2 seeds (results/g1_run3/REPORT.md, verification/V1d_numbers_v3grid.md).",
  "g2": rd("g2.json", True),
  "openai2024": rd("openai2024.json", True), "openai2024_numbers_md": rd("openai2024_numbers.md"),
  "openai2024_png_b64": base64.b64encode(png.read_bytes()).decode() if png.exists() else None,
  "verification_index": sorted(p.name for p in (ROOT / "verification").glob("*.md")),
  "human": human_summary(),
}
(ROOT / "app/static/precomputed.json").write_text(json.dumps(out))
# V5e concern C1 (2026-09-08): the full item dicts used by bring-your-own-key mode are no longer bundled into
# precomputed.json (fetched by every visitor). They go to app/private/byok_items.json, outside the /static mount,
# and are served only by GET /api/byok_items, which the page calls only when BYOK mode starts and which the operator
# can switch off with EST_SERVE_BYOK_ITEMS=0 for scored use.
priv = ROOT / "app" / "private"; priv.mkdir(exist_ok=True)
(priv / "byok_items.json").write_text(json.dumps({"items_b64_DEMO_ONLY_INSPECTABLE": base64.b64encode(json.dumps({i: load_item(i) for i in list_items()}).encode()).decode()}))
print("wrote app/private/byok_items.json")
print("wrote precomputed.json", {k: (len(v) if isinstance(v, (str, list)) else bool(v)) for k, v in out.items()})
