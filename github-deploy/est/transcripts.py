"""Post-trial transcript judge: scores any participant↔assistant transcript on the five EST constructs.
One LLM call per session (cached by content hash). See trial/SCHEMA.md for inputs."""
from __future__ import annotations
import functools, hashlib, json, os, pathlib
from est.llm import complete_json, SONNET

JUDGE_SYS = """You are a meticulous research assistant coding transcripts from a study of how well people extract
information from an AI assistant. You will be given: the TASK the participant was working on; a list of
TARGETS (the sub-questions / information items a fully thorough participant would have asked about; may be
empty, in which case first write your own list of 4-7 targets for this task and use it); the TRANSCRIPT
(USER = participant, ASSISTANT = model); and the participant's SUBMISSION (may be null).

Code every USER turn i (0-based over user turns only):
- "asks": list of target ids this turn asks about. Count a target only if the turn names its topic; a turn
  that merely restates the task or asks "anything else / what am I missing / any advice" names no target.
- "level": "specific" if the turn requests a concrete record, number, document, log, date, protocol step or
  otherwise pins down exactly what is wanted for at least one asked target; "general" if it names the topic
  only; "none" if it asks about no target.
- "retry": true if this turn re-asks, rephrases, narrows or pushes back on something the ASSISTANT failed to
  answer, deflected, refused, or answered vaguely in an earlier turn.
- "verify": true if this turn checks, challenges, cross-examines or asks for confirmation/sources of
  something the ASSISTANT said (including arithmetic or consistency checks).
Code every ASSISTANT turn j: "nonanswer": true if it declines, deflects, says it has no information, or gives
only generic content in response to a target-naming request.
Then: "provided": target ids for which the ASSISTANT gave substantive task-specific content anywhere;
"used": target ids whose assistant-provided content is reflected in the SUBMISSION (empty if no submission);
"targets_used": the target list you coded against (id -> topic), whether given or self-written;
"targets_given": true/false.
Return JSON: {"user_turns":[{"i":0,"asks":[],"level":"none","retry":false,"verify":false},...],
"assistant_turns":[{"j":0,"nonanswer":false},...], "provided":[], "used":[], "targets_used":{}, "targets_given":true,
"note":"<=30 words on anything unusual"}"""


def _render(task: dict | None, rec: dict) -> str:
    tg = (task or {}).get("targets") or {}
    lines = [f"TASK:\n{(task or {}).get('prompt', '(not supplied; infer from transcript)')}", "", "TARGETS:"]
    lines += [f"- {k}: {v.get('topic','')} — specific means e.g.: {v.get('detail','')[:160]}" for k, v in tg.items()] or ["(none supplied — write your own)"]
    lines += ["", "TRANSCRIPT:"]
    ui = aj = 0
    for m in rec["messages"]:
        if m["role"] == "user":
            lines.append(f"[USER {ui}] {m['content'].strip()}"); ui += 1
        else:
            lines.append(f"[ASSISTANT {aj}] {m['content'].strip()}"); aj += 1
    lines += ["", f"SUBMISSION:\n{rec.get('submission') or 'null'}"]
    return "\n".join(lines)


def session_hash(rec: dict, task: dict | None, model: str = SONNET) -> str:
    return hashlib.sha1((JUDGE_SYS + _render(task, rec) + model).encode()).hexdigest()[:16]


@functools.lru_cache(maxsize=None)
def _bundle(path: str) -> dict:
    try:
        return json.load(open(path)) if os.path.exists(path) else {}
    except Exception:
        return {}


def bundled_entries(cache_dir: str | os.PathLike) -> dict:
    """Shipped judge outputs for a cache directory. A repo ships `<cache_dir>.json` (one file: {"<hash>.json": output})
    instead of hundreds of small files; loose files in `<cache_dir>/` still take precedence. Read-only."""
    return _bundle(str(pathlib.Path(cache_dir)) + ".json")


def judge_session(rec: dict, task: dict | None, cache_dir: str | os.PathLike, model: str = SONNET) -> dict:
    prompt = _render(task, rec)
    h = session_hash(rec, task, model)
    cp = pathlib.Path(cache_dir) / f"{h}.json"
    if cp.exists():
        return json.load(open(cp))
    b = bundled_entries(cache_dir).get(cp.name)
    if b is not None:
        return b
    out = complete_json(JUDGE_SYS, [{"role": "user", "content": prompt}], model=model, max_tokens=3000)
    out["_hash"] = h
    cp.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(cp, "w"), indent=1)
    return out


def metrics(j: dict, target_ids: list | None) -> dict:
    """Five constructs from one judged session.
    Raw subscales keep NaN where undefined (persistence with no non-answers; uptake with nothing provided) so audits
    can count them. The COMPOSITE uses a fixed denominator of 5 with undefined persistence/uptake scored 0, so
    composites are comparable across sessions (a participant who never pushed far enough to meet a non-answer gets
    no persistence credit, matching EST refusal_recovery). composite_n_defined reports how many were observed."""
    nan = float("nan")
    def _sid(x): return str(x).strip()   # V59b B2: the judge may number self-written targets as integers while JSON object keys are strings; compare as strings everywhere
    tg = [_sid(t) for t in (list(target_ids) if target_ids else list((j.get("targets_used") or {}).keys()))]
    tgset = set(tg); n_t = len(tg) or 1
    uts = [dict(u, asks=[_sid(a) for a in (u.get("asks") or []) if a is not None]) if isinstance(u, dict) else {} for u in (j.get("user_turns") or [])]
    ats = [a if isinstance(a, dict) else {} for a in (j.get("assistant_turns") or [])]
    j = dict(j, provided=[_sid(x) for x in (j.get("provided") or []) if x is not None], used=[_sid(x) for x in (j.get("used") or []) if x is not None])
    asked = {a for u in uts for a in (u.get("asks") or []) if (not tgset or a in tgset)}
    on_target = [u for u in uts if any((not tgset or a in tgset) for a in (u.get("asks") or []))]
    coverage = len(asked) / n_t if tgset else min(1.0, len(asked) / n_t)
    specificity = (sum(u.get("level") == "specific" for u in on_target) / len(on_target)) if on_target else 0.0
    n_non = sum(bool(a.get("nonanswer")) for a in ats)
    n_retry = sum(bool(u.get("retry")) for u in uts)
    persistence = min(1.0, n_retry / n_non) if n_non else nan
    verification = 1.0 if any(u.get("verify") for u in uts) else 0.0
    prov = {x for x in (j.get("provided") or []) if (not tgset or x in tgset)}
    used = {x for x in (j.get("used") or []) if (not tgset or x in tgset)}
    uptake = (len(used & prov) / len(prov)) if prov else nan
    raw = {"coverage": coverage, "specificity": specificity, "persistence": persistence, "verification": verification, "uptake": uptake}
    filled = [v if v == v else 0.0 for v in raw.values()]
    specific_ids = {a for u in uts if u.get("level") == "specific" for a in (u.get("asks") or []) if (not tgset or a in tgset)}
    return {**raw, "composite": sum(filled) / 5.0, "composite_n_defined": sum(v == v for v in raw.values()),
            "n_user_turns": len(uts), "n_nonanswers": n_non, "n_retries": n_retry,
            # target yield = share of designer targets whose content reached the final answer (the achievement scale used by the elicitation ratio)
            "target_yield": (len(used) / n_t) if tgset else nan,
            "asked_ids": sorted(asked), "specific_ids": sorted(specific_ids), "provided_ids": sorted(prov), "used_ids": sorted(used),
            "judge_invented_ids": sorted({a for u in uts for a in (u.get("asks") or []) if tgset and a not in tgset})}
