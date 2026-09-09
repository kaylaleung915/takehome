"""Rank elicitation skill from EXISTING transcripts (owner request 2026-09-08: "i thought this elicitation skill test
could have also used existing transcripts as inputs then could also rank elicitation skill?").

Usage:
  .venv/bin/python rank_transcripts.py INPUT [--tasks tasks.yaml] [--out outdir] [--cache dir]
        [--format auto|schema|sharegpt|openai|csv|txtdir] [--id-field FIELD] [--participant-id ID]
        [--max-sessions N] [--workers 4]

INPUT formats (auto-detected unless --format is given):
  schema   JSONL in the trial/SCHEMA.md shape: {"participant_id","session_idx","task_id","messages":[{role,content}],"submission"}
  openai   JSON list / single object / JSONL of {"messages":[{"role","content"}]} (participant id from --id-field or a
           common id field if present; else one person per object, or one person for the whole input with --participant-id)
  sharegpt JSON/JSONL of {"conversations":[{"from":"human"|"gpt","value":...}]} (same id rules)
  csv      columns participant_id, session_idx, role, content (rows in conversation order; optional task_id, submission)
  txtdir   a directory of .txt files, one session per file, turns prefixed "User:" / "Assistant:" (multi-line turns
           allowed); participant id = filename prefix before "__" (else the stem). A single .txt file is also accepted;
           inside one text blob, a line of "===" separates sessions.

Scoring is exactly the post-trial pipeline's (analyze_trial.py): one transcript-judge call per unique session
(est.transcripts.judge_session, cached by content hash), est.transcripts.metrics for coverage / specificity /
persistence (refusal-recovery) / verification / uptake / composite, per-person = mean over sessions
(analyze_trial.SUBS, pandas mean, NaN skipped). Composite = mean of the five with undefined persistence/uptake scored 0
(fixed denominator), as in analyze_trial. Display rule added here (owner wording): persistence is NA when no non-answer
occurred, and verification is NA when the assistant provided nothing checkable and the participant verified nothing;
the analyze_trial-identical verification mean (zeros included) is kept as verification_incl0.

Outputs: outdir/sessions.csv, ranking.csv, ranking.md (boxed caveat first), ranking.json; summary on stdout.
"""

from __future__ import annotations
import argparse, csv, io, json, math, pathlib, re, sys, time, zlib
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np, pandas as pd, yaml
from scipy import stats
from est.transcripts import judge_session, metrics, session_hash, bundled_entries
from est.llm import complete_json, SONNET
import hashlib
from analyze_trial import SUBS  # ["coverage","specificity","persistence","verification","uptake","composite"]

BEHAVIOURS = [s for s in SUBS if s != "composite"]
B_BOOT = 2000
MIN_PERSONS_FOR_RELIABILITY = 20

CAVEAT = (
    "CAVEAT. Scores describe what the person did in these transcripts, as coded by one LLM judge call per session against a "
    "fixed checklist for the task. Rank people on at least 3 substantial sessions each and read the interval, not the point rank: "
    "one short session per person is mostly noise (single-session reliability 0.06-0.24 in PRISM, 0.14 in RealHumanEval). "
    "The checklist is the yardstick: supply your own (a trial's designer targets, or one item per line in the checklist box) "
    "so every run is scored against the same list; leave it empty and the tool writes one checklist per task, shows it, and scores everyone on that "
    "task against the same list, but a later run may write a different list, so copy the shown checklist back in if you want "
    "comparable numbers across runs. Measured on three free-form chats (2026-09-08): re-judging under the same list moved a "
    "session's overall by at most 0.06, but two independently written lists for the same task moved one session by 0.35 and "
    "across all lists seen it ranged 0.00 to 0.96, so for tasks with no designer checklist or grading rubric read coverage and "
    "specificity as relative to the shown list only. The overall score is the mean of the behaviours that could be observed in the session "
    "(persistence needs an assistant non-answer, verification needs something checkable, uptake needs a written submission); "
    "the count observed is shown next to it, and an overall built on two behaviours is weaker evidence than one built on five."
)

# ------------------------------------------------------------------------------------------- checklists (targets)
# Owner direction 2026-09-08 ("i think you overcomplicated this. can you simplify the task/ tool?"): one checklist per task,
# written once when none is supplied, shown in the output and reused for every session of that task, instead of a fresh
# judge-written target list inside every judge call.
CHECKLIST_SYS = """You write the scoring checklist for a study of how thoroughly people question an AI assistant.
You are given a TASK (its prompt if known, else opening messages from one or more sessions on it). Write the 4 to 7
distinct pieces of information or sub-questions a fully thorough person working on this task would ask the assistant
for. Each item: a short topic (<= 8 words) and one sentence saying what a precise, specific request for it would name
(a record, number, document, date, protocol step). Items must be about the task's substance, not about formatting,
tone or tool mechanics. Return JSON only: {"items":[{"topic":"...","detail":"..."}, ...]}"""
CHECKLIST_VERSION = "checklist-v1"


def _task_evidence(task_id: str, prompt: str | None, recs: list[dict], k: int = 3, n_chars: int = 1200) -> str:
    lines = [
        f"TASK ID: {task_id}",
        f"TASK PROMPT: {prompt.strip() if prompt else '(not supplied; infer the task from the openings below)'}",
    ]
    if not prompt:
        firsts = []
        for r in recs:
            u = next((m["content"] for m in r["messages"] if m["role"] == "user"), None)
            if u and u not in firsts:
                firsts.append(u)
            if len(firsts) >= k:
                break
        for n, u in enumerate(firsts):
            lines += ["", f"OPENING MESSAGE OF SESSION {n + 1}:", u.strip()[:n_chars]]
    return "\n".join(lines)


def checklist_hash(task_id: str, prompt: str | None, recs: list[dict], model: str = SONNET) -> str:
    return hashlib.sha1(
        (CHECKLIST_VERSION + CHECKLIST_SYS + _task_evidence(task_id, prompt, recs) + model).encode()
    ).hexdigest()[:16]


def derive_checklist(task_id: str, prompt: str | None, recs: list[dict], cache_dir, model: str = SONNET) -> dict:
    """One model call per task (cached under cache_dir/checklist_<hash>.json) -> targets dict {T1: {topic, detail}, ...}."""
    h = checklist_hash(task_id, prompt, recs, model)
    cp = pathlib.Path(cache_dir) / f"checklist_{h}.json"
    if cp.exists():
        return json.load(open(cp))["targets"]
    out = complete_json(
        CHECKLIST_SYS,
        [{"role": "user", "content": _task_evidence(task_id, prompt, recs)}],
        model=model,
        max_tokens=1200,
    )
    items = [it for it in (out.get("items") or []) if isinstance(it, dict) and str(it.get("topic") or "").strip()][:7]
    if len(items) < 2:
        raise ValueError(f"checklist writer returned {len(items)} usable items for task {task_id!r}")
    targets = {
        f"T{n + 1}": {"topic": str(it["topic"]).strip()[:120], "detail": str(it.get("detail") or "").strip()[:300]}
        for n, it in enumerate(items)
    }
    cp.parent.mkdir(parents=True, exist_ok=True)
    json.dump(
        {"task_id": task_id, "hash": h, "targets": targets, "written": time.strftime("%Y-%m-%d %H:%M:%S")},
        open(cp, "w"),
        indent=1,
    )
    return targets


def parse_checklist_text(text: str | None) -> dict:
    """Checklist box / --checklist file. Either one item per line (applies to every task in the input; 'topic: detail'
    optional), or a JSON object {task_id: [items or {topic, detail}], ...}. Returns {task_id or '*': targets dict}."""
    text = (text or "").strip().lstrip("\ufeff")
    if not text:
        return {}

    def _targets(items):
        out = {}
        for it in items:
            if isinstance(it, dict):
                topic, detail = str(it.get("topic") or "").strip(), str(it.get("detail") or "").strip()
            else:
                line = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)]|T\d+[:.)])\s*", "", str(it)).strip()
                topic, _, detail = line.partition(":")
                topic, detail = topic.strip(), detail.strip()
            if topic:
                out[f"T{len(out) + 1}"] = {"topic": topic[:120], "detail": detail[:300]}
            if len(out) >= 12:
                break
        return out

    if text[:1] == "{":
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError("checklist JSON must be an object {task_id: [items]}")
        res = {str(k): _targets(v if isinstance(v, list) else [v]) for k, v in obj.items()}
    else:
        res = {"*": _targets([ln for ln in text.splitlines() if ln.strip()])}
    res = {k: v for k, v in res.items() if v}
    if not res:
        raise ValueError("checklist had no usable items (one item per line, or JSON {task_id: [items]})")
    return res


def ensure_checklists(
    recs: list[dict],
    tasks: dict | None,
    cache_dir,
    checklist: dict | None = None,
    derive: bool = True,
    model: str = SONNET,
) -> tuple[dict, dict]:
    """Give every non-control task a target list before judging. Precedence per task_id: designer targets in `tasks`
    (source 'designer') > checklist[task_id] > checklist['*'] (source 'supplied') > one derive_checklist call (source
    'written by the tool'). Returns (tasks', info) where info[task_id] = {source, items{id: topic}, n_sessions}."""
    tasks = {k: dict(v) for k, v in (tasks or {}).items() if isinstance(v, dict)}
    checklist = checklist or {}
    info = {}
    by_task = {}
    for r in recs:
        if str(r["participant_id"]).startswith("control:") or str(r["task_id"]).startswith("control:"):
            continue
        by_task.setdefault(r["task_id"], []).append(r)
    failures = {}
    for tid, rs in by_task.items():
        t = tasks.get(tid) or {}
        if t.get("targets"):
            src = t.get("targets_source") or "designer"
        elif checklist.get(tid) or checklist.get("*"):
            t = {**t, "targets": checklist.get(tid) or checklist["*"], "targets_source": "supplied"}
            src = "supplied"
        elif derive:
            try:
                t = {
                    **t,
                    "targets": derive_checklist(tid, t.get("prompt"), rs, cache_dir, model),
                    "targets_source": "written by the tool",
                }
                src = "written by the tool"
            except (
                Exception
            ) as e:  # noqa: fall back to the judge writing its own list inside each call (old behaviour), flagged
                failures[tid] = f"{type(e).__name__}: {str(e)[:160]}"
                src = "judge, per call (checklist writer failed)"
        else:
            src = "judge, per call"
        if t.get("targets") and not t.get("prompt"):
            t["prompt"] = f"(not supplied; sessions labelled {tid!r}; infer the task from the transcript)"
        if t:
            tasks[tid] = t
        tg_ = t.get("targets") or {}
        info[tid] = {
            "source": src,
            "n_sessions": len(rs),
            "items": {k: (v.get("topic") if isinstance(v, dict) else str(v)) for k, v in tg_.items()},
            # V60 S2: copy-back lines carry the detail too, so a pasted-back checklist renders the same TARGETS block
            "lines": [
                (
                    (
                        str(v.get("topic", "")).replace(":", " -")
                        + (": " + str(v.get("detail")) if v.get("detail") else "")
                    )
                    if isinstance(v, dict)
                    else str(v)
                )
                for v in tg_.values()
            ],
        }
    return tasks, {"tasks": info, "failures": failures}


CONTROLS_DIR = ROOT / "controls"


def load_controls() -> tuple[list[dict], dict, dict]:
    """Anchor transcripts with established scores (controls/build_controls.py): returns (records, tasks, expected)."""
    recs = [json.loads(l) for l in open(CONTROLS_DIR / "anchors.jsonl", encoding="utf-8") if l.strip()]
    tasks = yaml.safe_load(open(CONTROLS_DIR / "tasks.yaml", encoding="utf-8")) or {}
    expected = json.load(open(CONTROLS_DIR / "expected.json", encoding="utf-8"))
    return recs, tasks, expected


def seed_controls_cache(cache_dir) -> int:
    """Copy the build-time judge outputs for the anchors into cache_dir so scoring them costs no new judge calls
    unless the judge prompt or model changed (the cache key hashes both), which is exactly when a fresh check is wanted.
    """
    cache_dir = pathlib.Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    src = CONTROLS_DIR / "judge_cache"
    for name, out in bundled_entries(src).items():  # shipped as one file, controls/judge_cache.json
        if not (cache_dir / name).exists():
            (cache_dir / name).write_text(json.dumps(out, indent=1))
            n += 1
    if src.exists():
        for f in src.glob("*.json"):
            if not (cache_dir / f.name).exists():
                (cache_dir / f.name).write_bytes(f.read_bytes())
                n += 1
    return n


def controls_report(S: pd.DataFrame, P: pd.DataFrame, expected: dict) -> dict:
    """Compare this run's judged scores on the anchors with their references. Scripted anchors: controller ground truth
    (from the server's release log via EST's own scorer, which uses the controller's per-turn LLM judge and a submission judge, so it is independent of the TRANSCRIPT judge, not of all LLM judging). Human anchors: the judge's own build-time score (stability check only).
    """
    tol = float(expected.get("tolerance_composite", 0.15))
    persons = []
    for pid, E in expected["persons"].items():
        row = P[P.participant_id == pid]
        now = {
            k: (None if not len(row) or row.iloc[0][k] != row.iloc[0][k] else round(float(row.iloc[0][k]), 3))
            for k in SUBS
        }
        ref = E.get("ground_truth") or E.get("judge_reference") or {}
        ref_kind = "controller ground truth" if E.get("ground_truth") else "judge reference (build time)"
        d = (
            None
            if now["composite"] is None or ref.get("composite") is None
            else round(abs(now["composite"] - ref["composite"]), 3)
        )
        persons.append(
            {
                "participant_id": pid,
                "kind": E.get("kind"),
                "label": E.get("label"),
                "reference_kind": ref_kind,
                "reference": {k: ref.get(k) for k in SUBS},
                "judge_reference": E.get("judge_reference"),
                "now": now,
                "abs_diff_composite": d,
                "within_tolerance": (None if d is None else d <= tol),
            }
        )
    diffs = [p["abs_diff_composite"] for p in persons if p["abs_diff_composite"] is not None]
    order_ref = [
        p["participant_id"]
        for p in sorted(
            persons, key=lambda p: (p["reference"].get("composite") is None, -(p["reference"].get("composite") or 0))
        )
    ]
    order_now = [
        p["participant_id"]
        for p in sorted(persons, key=lambda p: (p["now"]["composite"] is None, -(p["now"]["composite"] or 0)))
    ]
    ok = bool(diffs) and max(diffs) <= tol and order_ref == order_now
    return {
        "version": expected.get("version"),
        "judge_model_at_build": expected.get("judge_model"),
        "built_at": expected.get("built_at"),
        "tolerance_composite": tol,
        "n_anchor_sessions": expected.get("n_sessions"),
        "persons": persons,
        "max_abs_diff_composite": (max(diffs) if diffs else None),
        "order_preserved": order_ref == order_now,
        "controls_ok": ok,
        "message": (
            (
                "NOTE: unless run with --controls-fresh, anchor scores are replayed from the shipped judge outputs whenever the judge prompt and model string are unchanged, so this check detects prompt/model/formula changes, not sampling drift or silent backend updates. "
                if True
                else ""
            )
            + (
                "Controls reproduced: every anchor's composite is within %.2f of its reference and the anchor ordering is unchanged, so scores in this run are on the same scale as the references."
                % tol
            )
            if ok
            else (
                "Controls NOT reproduced (max composite difference %s, ordering preserved: %s): the judge has drifted or failed on an anchor; do not compare this run's scores with earlier runs."
                % (max(diffs) if diffs else "NA", order_ref == order_now)
            )
        ),
        "note": expected.get("note"),
    }


ID_FIELDS = ["participant_id", "user_id", "person_id", "programmer_id", "person", "user", "author", "participant", "id"]
USER_ROLES = {"user", "human", "participant", "student", "person"}
ASSIST_ROLES = {"assistant", "gpt", "ai", "model", "bot", "chatgpt", "claude", "system_assistant"}
TURN_RE = re.compile(r"^\s*(user|human|participant|assistant|ai|model|bot|gpt|claude)\s*:\s*", re.I)
SEP_RE = re.compile(r"^\s*={3,}\s*$")


# ----------------------------------------------------------------------------------------------------- parsing
def _norm_role(r: str) -> str | None:
    r = (r or "").strip().lower()
    if r in USER_ROLES:
        return "user"
    if r in ASSIST_ROLES:
        return "assistant"
    return None  # system / tool / unknown -> dropped


def _norm_messages(msgs) -> list[dict]:
    out = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        role = _norm_role(m.get("role") or m.get("from") or m.get("speaker") or "")
        content = m.get("content") if m.get("content") is not None else m.get("value", m.get("text", ""))
        if isinstance(content, list):  # OpenAI content parts
            content = "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        content = "" if content is None else str(content)
        if role is None or not content.strip():
            continue
        out.append(
            {"role": role, "content": content}
        )  # consecutive same-role turns are kept as-is (hash-identical to analyze_trial for schema input)
    return out


def parse_turn_text(text: str) -> list[dict]:
    """'User: ... / Assistant: ...' text -> messages (multi-line turns allowed)."""
    msgs, cur_role, buf = [], None, []
    for line in text.splitlines():
        m = TURN_RE.match(line)
        if m:
            if cur_role is not None:
                msgs.append({"role": cur_role, "content": "\n".join(buf).strip()})
            cur_role = _norm_role(m.group(1))
            buf = [line[m.end() :]]
        elif cur_role is not None:
            buf.append(line)
    if cur_role is not None:
        msgs.append({"role": cur_role, "content": "\n".join(buf).strip()})
    return _norm_messages(msgs)


FRAMES_SYS_LINE = re.compile(
    r"^[ \t]*\[(System|Memory|image:|document:|rolling-summary)[^\n]*$", re.M
)  # [ \t]* not \s*: linear on blank-line runs (V59b S6)
FRAMES_ATTACH_START = re.compile(r'\{"type"\s*:\s*"(?:attachment|artifact)"')
FRAMES_TAG = re.compile(
    r"\[attached: [^\[\]\n]*\]"
)  # excludes "[" so unmatched starts cannot rescan to end of line (V59b S6)
_CHIP_WINDOW = (
    4096  # raw_decode sees only this much after a chip start, so unterminated starts cost O(window) (V59b S6)
)
_CHIP_WINDOW_BIG = 65536  # V59c SF1: retried once per start when the text has few chip starts, so a real chip with long metadata still collapses
_CHIP_FEW = 64
_JSON_DEC = json.JSONDecoder()


def _chips_to_tags(txt: str) -> str:
    """Inline attachment/artifact JSON objects -> '[attached: <filename>]'. Linear scan with raw_decode for the exact object end
    (V59 B1/S2: the earlier lazy regex backtracked exponentially and could swallow typed text)."""
    out, pos = [], 0
    n_big = 0  # V60 S6: the 65,536-byte retry is allowed for the first _CHIP_FEW starts in a message (was: disabled entirely beyond 64 starts)
    while True:
        m = FRAMES_ATTACH_START.search(txt, pos)
        if not m:
            out.append(txt[pos:])
            break
        out.append(txt[pos : m.start()])
        try:
            try:
                obj, end = _JSON_DEC.raw_decode(txt[m.start() : m.start() + _CHIP_WINDOW])
            except ValueError:
                if n_big >= _CHIP_FEW:
                    raise
                n_big += 1
                obj, end = _JSON_DEC.raw_decode(txt[m.start() : m.start() + _CHIP_WINDOW_BIG])
            end += m.start()
        except (ValueError, RecursionError):
            out.append(txt[m.start() : m.end()])
            pos = m.end()
            continue
        name = obj.get("filename") if isinstance(obj, dict) else None
        name = re.sub(r"[\[\]\n]", "_", str(name))[:120] if name else "file"  # keep the tag matchable by FRAMES_TAG
        out.append(f"[attached: {name}]")
        pos = end
    return "".join(out)


def _flagged(v) -> bool:
    """Harness flag present and not null/false (same rule as the page's slimExport; V59 S5)."""
    return v is not None and v is not False


def _frames_root(o: dict) -> dict | None:
    """Agent-session export ({export_version, root_frame_id, frames:[...]}, v1.4.3): the root frame holds the human conversation;
    child frames are sub-agents and are ignored."""
    frames = [f for f in (o.get("frames") or []) if isinstance(f, dict)]
    if not frames:
        return None
    rid = o.get("root_frame_id")
    root = (
        next((f for f in frames if rid and f.get("id") == rid), None)
        or next((f for f in frames if f.get("parent_frame_id") in (None, "")), None)
        or frames[0]
    )
    return root if isinstance(root.get("messages"), list) else None


def _frames_messages(root: dict) -> list[dict]:
    """Keep what the person typed and what the assistant said in prose. Dropped: harness notices, rolling summaries, tool calls
    and tool results, thinking, images, '[System] Attached file' preview lines; inline attachment JSON becomes '[attached: name]'.
    Assistant prose fragments split by tool calls are merged into one turn. Typed user turns are never merged: two of them
    separated only by assistant tool work (no prose) get a one-line placeholder assistant turn between them so the judge sees
    the gap; two with nothing at all from the assistant in between stay as consecutive user turns (V59 N9: a resend or
    "try again" must stay visible)."""
    out: list[dict] = []
    tools_since = 0  # assistant tool_use blocks seen since the last emitted turn
    for m in root.get("messages") or []:
        if not isinstance(m, dict) or _flagged(m.get("_harness_notice")) or _flagged(m.get("_rolling_summary")):
            continue
        role = _norm_role(str(m.get("role") or ""))
        if role is None:
            continue
        c = m.get("content")
        if isinstance(c, list):
            txt = "\n".join(str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            if role == "assistant":
                tools_since += sum(1 for b in c if isinstance(b, dict) and b.get("type") == "tool_use")
        else:
            txt = "" if c is None else str(c)
        if role == "user":
            txt = _chips_to_tags(txt)
            txt = FRAMES_SYS_LINE.sub("", txt)
            if not FRAMES_TAG.sub("", txt).strip():
                txt = ""  # an attachment with no typed words is not a turn (linear; V59 B1)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        if not txt:
            continue
        if out and out[-1]["role"] == role == "assistant":
            out[-1]["content"] += "\n\n" + txt
        else:
            if role == "user" and out and out[-1]["role"] == "user" and tools_since:
                out.append(
                    {
                        "role": "assistant",
                        "content": f"[worked with tools ({tools_since} call{'s' if tools_since != 1 else ''}); no prose reply before the next message]",
                    }
                )
            out.append({"role": role, "content": txt})
        tools_since = 0
    if out and out[-1]["role"] == "user" and tools_since:
        out.append(
            {
                "role": "assistant",
                "content": f"[worked with tools ({tools_since} call{'s' if tools_since != 1 else ''}); no prose reply]",
            }
        )
    return out


def _obj_to_record(o: dict, default_pid: str, idx: int, id_field: str | None) -> dict | None:
    root = _frames_root(o) if isinstance(o.get("frames"), list) else None
    if root is not None:
        summ = o.get("summary")
        email = str((summ.get("user_email") if isinstance(summ, dict) else "") or "").split("@")[0].strip()
        name = str(o.get("conversation_name") or root.get("task_summary") or "").strip()
        return {
            "participant_id": email or default_pid,
            "_pid_from_field": bool(email),
            "session_idx": None,
            "task_id": (name[:80] or "unspecified"),
            "messages": _frames_messages(root),
            "submission": None,
            "_format": "frames",
        }
    if "messages" in o:
        msgs = _norm_messages(o["messages"])
    elif "conversations" in o:
        msgs = _norm_messages(o["conversations"])
    elif "conversation" in o:
        msgs = _norm_messages(o["conversation"])
    elif "transcript" in o and isinstance(o["transcript"], str):
        msgs = parse_turn_text(o["transcript"])
    else:
        return None
    pid = None
    for f in ([id_field] if id_field else []) + ID_FIELDS:
        if f and o.get(f) not in (None, ""):
            pid = str(o[f])
            break
    return {
        "participant_id": pid or default_pid,
        "_pid_from_field": pid is not None,
        "session_idx": o.get("session_idx"),
        "task_id": str(o.get("task_id") or o.get("task") or "unspecified"),
        "messages": msgs,
        "submission": o.get("submission"),
    }


def _load_json_objects(text: str) -> list | None:
    text = text.strip().lstrip("\ufeff").strip()  # BOM-tolerant (V59b N17)
    if not text:
        return None
    try:
        j = json.loads(text)
        if isinstance(j, dict):
            if isinstance(j.get("frames"), list):
                return [j]  # V59 N1: an export wins over generic list keys
            for k in ("transcripts", "sessions", "data", "records"):
                if isinstance(j.get(k), list):
                    return j[k]
            return [j]
        if isinstance(j, list):
            return j
    except json.JSONDecodeError:
        pass
    objs = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            objs.append(json.loads(ln))
        except json.JSONDecodeError:
            return None
    return objs if objs and all(isinstance(o, dict) for o in objs) else None


def _parse_csv_text(text: str) -> list[dict]:
    rd = csv.DictReader(io.StringIO(text))
    need = {"participant_id", "session_idx", "role", "content"}
    if not rd.fieldnames or not need <= set(rd.fieldnames):
        raise ValueError(f"csv needs columns {sorted(need)}; got {rd.fieldnames}")
    sess: dict[tuple, dict] = {}
    for row in rd:
        key = (str(row["participant_id"]), str(row["session_idx"]))
        r = sess.setdefault(
            key,
            {
                "participant_id": key[0],
                "session_idx": row["session_idx"],
                "task_id": str(row.get("task_id") or "unspecified"),
                "messages": [],
                "submission": None,
            },
        )
        r["messages"].append({"role": row["role"], "content": row["content"]})
        if row.get("submission"):
            r["submission"] = row["submission"]
    out = []
    for r in sess.values():
        r["messages"] = _norm_messages(r["messages"])
        out.append(r)
    return out


def parse_text_blob(
    text: str, default_pid: str = "anon", fmt: str = "auto", id_field: str | None = None, force_pid: str | None = None
) -> tuple[list[dict], str]:
    """Any single text blob (file content or pasted text) -> (records, detected_format)."""
    if text and text[:1] == "\ufeff":
        text = text[1:]  # V59c SF5: one leading BOM (Excel/Notepad) stripped once for every format, incl. txt and csv
    recs, detected = [], None
    objs = None if fmt in ("csv", "txt", "txtdir") else _load_json_objects(text)
    if objs is not None:
        for i, o in enumerate(objs):
            if not isinstance(o, dict):
                continue
            r = _obj_to_record(o, default_pid if len(objs) == 1 else f"{default_pid}_{i:03d}", i, id_field)
            if r:
                recs.append(r)
        if objs and isinstance(objs[0], dict):
            detected = (
                "frames"
                if isinstance(objs[0].get("frames"), list)
                else (
                    "schema"
                    if ("participant_id" in objs[0] and "messages" in objs[0])
                    else "sharegpt" if "conversations" in objs[0] else "openai"
                )
            )
    elif fmt == "csv" or (
        fmt == "auto" and re.match(r"^\W*participant_id\s*,", text.lstrip()[:200]) and "role" in text.splitlines()[0]
    ):
        recs = _parse_csv_text(text)
        detected = "csv"
    else:
        chunks, cur = [], []
        for line in text.splitlines():
            if SEP_RE.match(line):
                chunks.append("\n".join(cur))
                cur = []
            else:
                cur.append(line)
        chunks.append("\n".join(cur))
        for i, ch in enumerate(c for c in chunks if c.strip()):
            msgs = parse_turn_text(ch)
            if msgs:
                recs.append(
                    {
                        "participant_id": default_pid,
                        "session_idx": i,
                        "task_id": "unspecified",
                        "messages": msgs,
                        "submission": None,
                    }
                )
        detected = "txt"
    if force_pid:
        for r in recs:
            r["participant_id"] = force_pid
    return recs, detected or "unknown"


def _looks_like_export(text: str) -> bool:
    head = text.lstrip("\ufeff \t\r\n")[:4000]  # BOM-tolerant (V59b N17)
    return head.startswith("{") and ('"frames"' in head or '"export_version"' in head or '"root_frame_id"' in head)


def load_input(
    path: str, fmt: str = "auto", id_field: str | None = None, force_pid: str | None = None
) -> tuple[list[dict], str]:
    p = pathlib.Path(path)
    if p.is_dir():
        files = sorted(list(p.glob("*.txt")))
        if not files:
            raise ValueError(f"no .txt files in {p}")
        recs = []
        for i, f in enumerate(files):
            stem = f.stem
            pid = stem.split("__")[0] if "__" in stem else stem
            rs, _ = parse_text_blob(f.read_text(errors="replace"), default_pid=pid, fmt="txt", force_pid=force_pid)
            for k, r in enumerate(rs):
                r["participant_id"] = force_pid or pid
                r["session_idx"] = None
                r["_file"] = f.name
            recs += rs
        return _finalise(recs), "txtdir"
    text = p.read_text(errors="replace")
    eff = fmt
    if fmt == "auto" and p.suffix.lower() == ".csv":
        eff = "csv"
    if fmt == "auto" and p.suffix.lower() == ".txt" and not _looks_like_export(text):
        eff = "txt"
    recs, det = parse_text_blob(
        text, default_pid=p.stem.split("__")[0], fmt=eff, id_field=id_field, force_pid=force_pid
    )
    return _finalise(recs), det


def _finalise(recs: list[dict]) -> list[dict]:
    """Assign session_idx where missing (order of appearance per participant), drop empty sessions, strip helper keys."""
    out, counters = [], {}
    for r in recs:
        msgs = r.get("messages") or []
        if not any(m["role"] == "user" for m in msgs):
            continue
        pid = str(r.get("participant_id") or "anon")
        si = r.get("session_idx")
        try:
            si = int(si)
        except (TypeError, ValueError):
            si = None
        if si is None:
            si = counters.get(pid, 0)
        counters[pid] = max(counters.get(pid, 0), si + 1)
        sub = r.get("submission")
        out.append(
            {
                "participant_id": pid,
                "session_idx": si,
                "task_id": str(r.get("task_id") or "unspecified"),
                "messages": [{"role": m["role"], "content": m["content"]} for m in msgs],
                "submission": (None if sub in (None, "") else str(sub)),
            }
        )
    return out


def total_chars(recs: list[dict]) -> int:
    return sum(len(m["content"]) for r in recs for m in r["messages"]) + sum(len(r["submission"] or "") for r in recs)


# ----------------------------------------------------------------------------------------------------- scoring
JUDGE_MODELS = {
    "claude-sonnet-5": "claude-sonnet-5",
    "sonnet": "claude-sonnet-5",
    "claude-opus-5": "claude-opus-5",
    "opus": "claude-opus-5",
}


def score_records(
    recs: list[dict], tasks: dict | None, cache_dir, workers: int = 4, model: str = SONNET
) -> tuple[pd.DataFrame, dict]:
    """Judge each unique session once (cached) and compute the five constructs exactly as analyze_trial.py does."""
    tasks = tasks or {}
    cache_dir = pathlib.Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    uniq = {}
    for rec in recs:
        uniq.setdefault(session_hash(rec, tasks.get(rec["task_id"]), model), rec)
    new_calls = sum(not (cache_dir / f"{h}.json").exists() for h in uniq)
    failures = {}

    def _j(h):
        try:
            return judge_session(uniq[h], tasks.get(uniq[h]["task_id"]), cache_dir, model=model)
        except Exception as e:  # noqa
            failures[h] = f"{type(e).__name__}: {str(e)[:160]}"
            return None

    t0 = time.time()
    with ThreadPoolExecutor(max(1, workers)) as ex:
        judged = dict(zip(uniq.keys(), ex.map(_j, list(uniq.keys()))))
    rows = []
    for rec in recs:
        task = tasks.get(rec["task_id"])
        h = session_hash(rec, task, model)
        j = judged.get(h)  # V60 B1: was model-less, so a non-default judge model scored nothing
        base = {
            "participant_id": rec["participant_id"],
            "session_idx": rec["session_idx"],
            "task_id": rec["task_id"],
            "targets_given": bool((task or {}).get("targets")),
            "targets_source": (
                ((task or {}).get("targets_source") or "designer") if (task or {}).get("targets") else "judge, per call"
            ),
            "transcript_hash": h,
            "n_user_msgs": sum(m["role"] == "user" for m in rec["messages"]),
            "n_chars": sum(len(m["content"]) for m in rec["messages"]),
        }
        if j is None:
            rows.append({**base, "judged": False})
            continue
        m = metrics(j, list(((task or {}).get("targets") or {}).keys()) or None)
        # display rule: verification undefined when nothing checkable was provided and nothing was verified
        ver_opp = bool(m["provided_ids"]) or m["verification"] == 1.0
        has_sub = bool(rec.get("submission"))
        shown = {
            "coverage": m["coverage"],
            "specificity": m["specificity"],
            "persistence": m["persistence"],
            "verification": (m["verification"] if ver_opp else float("nan")),
            "uptake": (m["uptake"] if has_sub else float("nan")),
        }
        obs = [v for v in shown.values() if v == v]
        rows.append(
            {
                **base,
                "judged": True,
                **m,
                "has_submission": has_sub,
                "verification_incl0": m["verification"],
                "verification": shown["verification"],
                "uptake_incl0": m["uptake"],
                "uptake": shown["uptake"],
                "overall": (sum(obs) / len(obs)) if obs else float("nan"),
                "n_observed": len(
                    obs
                ),  # section 2 headline: mean of observed behaviours (owner simplification 2026-09-08); `composite` keeps the trial definition (fixed /5)
                "n_targets": len(j.get("targets_used") or {}) if not base["targets_given"] else len(task["targets"]),
                "judge_note": (j.get("note") or "")[:200],
            }
        )
    S = pd.DataFrame(rows)
    info = {
        "n_records": len(recs),
        "n_unique_transcripts": len(uniq),
        "new_judge_calls": int(new_calls),
        "judge_failures": failures,
        "judge_seconds": round(time.time() - t0, 1),
        "tasks_without_designer_targets": (
            sorted(S[S.targets_source != "designer"].task_id.unique().tolist()) if len(S) else []
        ),
    }
    return S, info


def _boot_mean_ci(x: np.ndarray, seed: int = 0) -> tuple[float, float]:
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(B_BOOT, len(x)), replace=True).mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def aggregate_persons(S: pd.DataFrame) -> pd.DataFrame:
    """Per-person means exactly as analyze_trial.py (S.groupby('participant_id')[SUBS].mean(), NaN skipped), plus
    n_sessions, bootstrap CI on the composite (n_sessions >= 2), rank (1 = highest composite) and percentile."""
    Sj = S[S.judged] if "judged" in S else S
    if not len(Sj):
        return pd.DataFrame()
    g = Sj.groupby("participant_id")
    prof = g[SUBS + ["overall", "verification_incl0", "uptake_incl0"]].mean()
    prof["n_observed_mean"] = g.n_observed.mean().round(2)
    prof["n_sessions"] = g.size()
    prof["n_user_msgs_total"] = g.n_user_msgs.sum()
    prof["n_sessions_persistence_defined"] = g.persistence.apply(lambda s: int(s.notna().sum()))
    prof["n_sessions_verification_defined"] = g.verification.apply(lambda s: int(s.notna().sum()))
    prof["n_sessions_uptake_defined"] = g.uptake.apply(lambda s: int(s.notna().sum()))
    prof["any_task_without_designer_targets"] = ~g.targets_given.all()
    cis = {pid: _boot_mean_ci(gg.composite.values, seed=zlib.crc32(str(pid).encode())) for pid, gg in g}
    prof["composite_ci95_lo"] = [cis[p][0] for p in prof.index]
    prof["composite_ci95_hi"] = [cis[p][1] for p in prof.index]
    cio = {pid: _boot_mean_ci(gg.overall.dropna().values, seed=zlib.crc32(str(pid).encode())) for pid, gg in g}
    prof["overall_ci95_lo"] = [cio[p][0] for p in prof.index]
    prof["overall_ci95_hi"] = [cio[p][1] for p in prof.index]
    key = prof.overall.fillna(-1.0)  # rank on the observed-behaviour mean; composite (trial definition) kept alongside
    prof["rank"] = key.rank(ascending=False, method="min").astype(int)
    prof["percentile"] = (key.rank(pct=True, method="average") * 100).round(1)
    prof["rank_by_composite"] = prof.composite.rank(ascending=False, method="min").astype(int)
    prof = prof.sort_values(["rank", "participant_id"]).reset_index()
    cols = (
        ["rank", "participant_id", "n_sessions"]
        + BEHAVIOURS
        + [
            "overall",
            "n_observed_mean",
            "overall_ci95_lo",
            "overall_ci95_hi",
            "composite",
            "composite_ci95_lo",
            "composite_ci95_hi",
            "rank_by_composite",
            "percentile",
            "verification_incl0",
            "uptake_incl0",
            "n_user_msgs_total",
            "n_sessions_persistence_defined",
            "n_sessions_verification_defined",
            "n_sessions_uptake_defined",
            "any_task_without_designer_targets",
        ]
    )
    return prof[cols]


def icc1(df: pd.DataFrame, col: str, cluster: str = "participant_id") -> float:
    """One-way random-effects ICC(1), persons with >=2 sessions, unbalanced k0 (same formula as the build-time RealHumanEval analysis, not shipped)."""
    d = df[[cluster, col]].dropna()
    ni = d.groupby(cluster)[col].size()
    d = d[d[cluster].isin(ni[ni >= 2].index)]
    g = d.groupby(cluster)[col]
    ni = g.size()
    a = len(ni)
    N = int(ni.sum())
    if a < 3 or N - a <= 0:
        return float("nan")
    grand = d[col].mean()
    ssb = float((ni * (g.mean() - grand) ** 2).sum())
    ssw = float(((d[col] - g.transform("mean")) ** 2).sum())
    msb = ssb / (a - 1)
    msw = ssw / (N - a)
    k0 = (N - (ni**2).sum() / N) / (a - 1)
    den = msb + (k0 - 1) * msw
    return float((msb - msw) / den) if den > 0 else float("nan")


def reliability(S: pd.DataFrame) -> dict:
    Sj = S[S.judged] if "judged" in S else S
    sizes = Sj.groupby("participant_id").size() if len(Sj) else pd.Series(dtype=int)
    n_ge2 = int((sizes >= 2).sum())
    out = {
        "n_persons": int(len(sizes)),
        "n_persons_ge2_sessions": n_ge2,
        "min_persons_required": MIN_PERSONS_FOR_RELIABILITY,
    }
    if n_ge2 < MIN_PERSONS_FOR_RELIABILITY:
        out["status"] = "insufficient repeat sessions"
        out["message"] = (
            f"insufficient repeat sessions ({n_ge2} persons with >=2 sessions; need >={MIN_PERSONS_FOR_RELIABILITY}) - no reliability estimate, treat the ranking as unvalidated"
        )
        return out
    out["status"] = "ok"
    per = {}
    for sub in SUBS + ["overall"]:
        rows = []
        for pid, g in Sj.sort_values("session_idx").groupby("participant_id"):
            if len(g) < 2:
                continue
            v = g[sub].values.astype(float)
            with np.errstate(all="ignore"):
                rows.append(
                    {
                        "odd": np.nanmean(v[0::2]) if np.any(~np.isnan(v[0::2])) else np.nan,
                        "even": np.nanmean(v[1::2]) if np.any(~np.isnan(v[1::2])) else np.nan,
                        "k": len(g),
                    }
                )
        H = pd.DataFrame(rows).dropna()
        if len(H) >= 3 and H.odd.nunique() > 1 and H.even.nunique() > 1:
            sp = stats.spearmanr(H.odd, H.even)
            pr = stats.pearsonr(H.odd, H.even)
            sb = (
                (2 * sp.statistic / (1 + sp.statistic)) if sp.statistic > -1 else float("nan")
            )  # V18: step up the Spearman split-half (was Pearson)
            per[sub] = {
                "n_persons": int(len(H)),
                "median_sessions": float(H.k.median()),
                "split_half_spearman": round(float(sp.statistic), 3),
                "p": round(float(sp.pvalue), 4),
                "spearman_brown": round(float(sb), 3),
                "icc1": round(icc1(Sj, sub), 3),
            }
        else:
            per[sub] = {
                "n_persons": int(len(H)),
                "split_half_spearman": None,
                "icc1": round(icc1(Sj, sub), 3),
                "note": "too few defined halves or no variance",
            }
    out["per_measure"] = per
    c = per.get("overall", {})
    out["message"] = (
        f"overall score split-half Spearman (odd vs even sessions) {c.get('split_half_spearman')} over {c.get('n_persons')} persons, "
        f"Spearman-Brown {c.get('spearman_brown')}, ICC(1) {c.get('icc1')}"
    )
    return out


# ----------------------------------------------------------------------------------------------------- outputs
def _f(x, nd=3):
    if x is None:
        return "NA"
    if isinstance(x, (float, np.floating)):
        return "NA" if x != x else f"{x:.{nd}f}"
    if isinstance(x, (bool, np.bool_)):
        return "yes" if x else "no"
    return str(x)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (float, np.floating)):
        return None if (o != o or o in (float("inf"), float("-inf"))) else float(o)
    return o


def build_result(S: pd.DataFrame, info: dict, tasks_given: bool, expected: dict | None = None) -> dict:
    P = aggregate_persons(S)
    is_ctl = S.participant_id.astype(str).str.startswith("control:") if len(S) else pd.Series(dtype=bool)
    rel = reliability(S[~is_ctl] if len(S) else S)  # reliability of the USER's ranking only
    if len(P):
        P["is_control"] = P.participant_id.astype(str).str.startswith("control:")
        P["rank_excluding_controls"] = P.composite.where(~P.is_control).rank(ascending=False, method="min")
    ctl = controls_report(S, P, expected) if (expected and len(P)) else None
    sess_cols = (
        [
            "participant_id",
            "session_idx",
            "task_id",
            "judged",
            "targets_given",
            "targets_source",
            "n_user_msgs",
            "n_chars",
        ]
        + BEHAVIOURS
        + [
            "overall",
            "n_observed",
            "composite",
            "composite_n_defined",
            "verification_incl0",
            "uptake_incl0",
            "has_submission",
            "n_user_turns",
            "n_nonanswers",
            "n_retries",
            "n_targets",
            "asked_ids",
            "specific_ids",
            "provided_ids",
            "used_ids",
            "judge_invented_ids",
            "transcript_hash",
            "judge_note",
        ]
    )
    Sx = S.reindex(columns=[c for c in sess_cols if c in S.columns]).sort_values(["participant_id", "session_idx"])
    comp = P[~P.is_control].composite if len(P) else pd.Series(dtype=float)
    ov = P[~P.is_control].overall.dropna() if len(P) else pd.Series(dtype=float)

    def _dist(x):
        return (
            {
                "mean": round(float(x.mean()), 3),
                "sd": round(float(x.std()), 3) if len(x) > 1 else None,
                "min": round(float(x.min()), 3),
                "median": round(float(x.median()), 3),
                "max": round(float(x.max()), 3),
            }
            if len(x)
            else None
        )

    summary = {
        "overall_distribution": _dist(ov),
        "checklists": (info.get("checklists") or {}).get("tasks", {}),
        "checklist_failures": (info.get("checklists") or {}).get("failures", {}),
        "n_sessions_input": info["n_records"],
        "n_sessions_scored": int(S.judged.sum()) if len(S) else 0,
        "n_persons": int(len(P)),
        "n_unique_transcripts": info["n_unique_transcripts"],
        "new_judge_calls": info["new_judge_calls"],
        "judge_model": info.get("judge_model", SONNET),
        "judge_failures": len(info["judge_failures"]),
        "tasks_yaml_supplied": tasks_given,
        "tasks_without_designer_targets": info["tasks_without_designer_targets"],
        "composite_distribution": (
            {
                "mean": round(float(comp.mean()), 3),
                "sd": round(float(comp.std()), 3) if len(comp) > 1 else None,
                "min": round(float(comp.min()), 3),
                "median": round(float(comp.median()), 3),
                "max": round(float(comp.max()), 3),
            }
            if len(comp)
            else None
        ),
        "persons_with_1_session": int((P.n_sessions == 1).sum()) if len(P) else 0,
        "persons_with_ge3_sessions": int((P.n_sessions >= 3).sum()) if len(P) else 0,
    }
    if len(P):
        Pu = P[~P.is_control]
        summary.update(
            {
                "n_persons": int(len(Pu)),
                "persons_with_1_session": int((Pu.n_sessions == 1).sum()),
                "persons_with_ge3_sessions": int((Pu.n_sessions >= 3).sum()),
                "n_control_persons": int(P.is_control.sum()),
                "n_control_sessions": int(is_ctl.sum()),
            }
        )
    return {
        "caveat": CAVEAT,
        "summary": summary,
        "reliability": rel,
        "controls": (_jsonable(ctl) if ctl else None),
        "persons": _jsonable(P.replace({np.nan: None}).to_dict("records")),
        "sessions": _jsonable(Sx.replace({np.nan: None}).to_dict("records")),
        "_P": P,
        "_S": Sx,
    }


def write_outputs(res: dict, out: pathlib.Path, source: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    P, Sx = res["_P"], res["_S"]
    P.to_csv(out / "ranking.csv", index=False, na_rep="NA")
    Sx.to_csv(out / "sessions.csv", index=False, na_rep="NA")
    json.dump({k: v for k, v in res.items() if not k.startswith("_")}, open(out / "ranking.json", "w"), indent=1)
    s, rel = res["summary"], res["reliability"]
    import textwrap

    box_w = 100
    lines = textwrap.wrap(CAVEAT, box_w - 4)
    box = (
        ["```", "+" + "-" * (box_w - 2) + "+"]
        + [f"| {ln.ljust(box_w - 4)} |" for ln in lines]
        + ["+" + "-" * (box_w - 2) + "+", "```"]
    )
    L = box + [
        "",
        "# Elicitation ranking from existing transcripts",
        "",
        f"Source: `{source}`. {s['n_sessions_scored']} of {s['n_sessions_input']} sessions scored ({s['n_unique_transcripts']} unique transcripts; "
        f"{s['new_judge_calls']} new judge calls, {s['judge_failures']} judge failures), {s['n_persons']} persons "
        f"({s['persons_with_1_session']} with a single session, {s['persons_with_ge3_sessions']} with >=3).",
        f"Designer targets (tasks.yaml) supplied: {'yes' if s['tasks_yaml_supplied'] else 'no'}.",
    ]
    if s.get("checklists"):
        L += ["", "## Checklist each task was scored against", ""]
        for tid, c in s["checklists"].items():
            L += [
                f"- `{tid}` ({c['source']}, {c['n_sessions']} sessions): "
                + (
                    "; ".join(f"{k} {v}" for k, v in c["items"].items())
                    or "(none: the judge wrote its own list inside each call)"
                )
            ]
        if any(c["source"] == "written by the tool" for c in s["checklists"].values()):
            L += [
                "",
                "A checklist written by the tool is written once per run and reused for every session of that task. To score later uploads against the same list, save these lines to a file and pass --checklist.",
            ]
    if s["overall_distribution"]:
        c = s["overall_distribution"]
        L += [
            "",
            f"Per-person overall score: mean {_f(c['mean'])}, SD {_f(c['sd'])}, min {_f(c['min'])}, median {_f(c['median'])}, max {_f(c['max'])}.",
        ]
    L += ["", "## Reliability of this ranking", "", rel["message"] + "."]
    if rel["status"] == "ok":
        L += [
            "",
            "| measure | persons (>=2 sessions) | split-half Spearman | Spearman-Brown | ICC(1) |",
            "|---|---|---|---|---|",
        ]
        for k, v in rel["per_measure"].items():
            L += [
                f"| {k} | {v.get('n_persons')} | {_f(v.get('split_half_spearman'))} | {_f(v.get('spearman_brown'))} | {_f(v.get('icc1'))} |"
            ]
        L += [
            "",
            "Split-half: each person's sessions ordered by session_idx, odd-position vs even-position means, Spearman across persons. ICC(1): one-way random-effects share of single-session variance that is between-person (persons with >=2 sessions).",
        ]
    c = res.get("controls")
    if c:
        L += [
            "",
            "## Controls (anchor transcripts scored in this run)",
            "",
            c["message"],
            "",
            "| anchor | reference kind | reference composite | this run | abs diff | within %.2f |"
            % c["tolerance_composite"],
            "|---|---|---|---|---|---|",
        ]
        for pz in c["persons"]:
            L += [
                f"| {pz['participant_id']} | {pz['reference_kind']} | {_f(pz['reference'].get('composite'))} | {_f(pz['now'].get('composite'))} | {_f(pz['abs_diff_composite'])} | {pz['within_tolerance']} |"
            ]
        L += ["", c.get("note") or ""]
    L += [
        "",
        "## Ranking (1 = highest overall score)",
        "",
        "| rank | person | n sessions | coverage | specificity | persistence | verification | uptake | overall | observed (of 5) | 95% CI (overall) | trial composite | percentile |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in P.iterrows():
        ci = f"{_f(r.overall_ci95_lo)} to {_f(r.overall_ci95_hi)}" if r.n_sessions >= 2 else "NA (1 session)"
        L += [
            f"| {r['rank']} | {r.participant_id}{' (control)' if r.get('is_control', False) else ''} | {r.n_sessions} | {_f(r.coverage)} | {_f(r.specificity)} | {_f(r.persistence)} | {_f(r.verification)} | {_f(r.uptake)} | {_f(r.overall)} | {r.n_observed_mean} | {ci} | {_f(r.composite)} | {_f(r.percentile, 1)} |"
        ]
    L += [
        "",
        "Columns: overall = mean of the behaviours that could be observed in each session (count shown), averaged over the person's sessions; "
        "trial composite = the post-trial pipeline's definition (mean of all five with unobserved counted as 0), kept for comparability with analyze_trial.py; "
        "coverage = share of checklist items the person asked about; specificity = share of on-target turns that pinned down exactly what was wanted; "
        "persistence = retries per assistant non-answer (NA if no non-answer occurred); verification = whether the person checked or challenged something the assistant said "
        "(NA if nothing checkable was provided); uptake = share of provided target content reflected in the submission (NA if nothing was provided or the session has no submission). "
        "Per-person values are means over that person's sessions with NA skipped; `verification_incl0` and `uptake_incl0` in ranking.csv are the analyze_trial-identical means (verification zeros kept; uptake 0 when content was provided but there was no submission). "
        "The 95% CI is a percentile bootstrap over the person's own sessions (2000 resamples) and says nothing about judge error.",
        "",
        "Per-session rows: sessions.csv. Machine-readable: ranking.json. Judge prompt: est/transcripts.py. Scoring functions: est.transcripts.metrics and analyze_trial.SUBS (imported, not re-implemented).",
    ]
    (out / "ranking.md").write_text("\n".join(L) + "\n")


def run(
    recs: list[dict],
    tasks: dict | None,
    cache_dir,
    workers: int = 4,
    controls: bool = False,
    controls_fresh: bool = False,
    checklist: dict | None = None,
    derive_checklists: bool = True,
    judge_model: str = SONNET,
) -> dict:
    """checklist / derive_checklists: see ensure_checklists (one pinned target list per task before judging).
    controls=True appends the anchor transcripts (controls/) to this run, scores them with the same judge in the same
    batch, flags them is_control in the persons table and returns a 'controls' block comparing now vs reference."""
    expected = None
    if controls:
        c_recs, c_tasks, expected = load_controls()
        if (
            controls_fresh
        ):  # genuine drift check: re-judge the anchors now instead of replaying the shipped judge outputs
            cache_dir = pathlib.Path(cache_dir) / time.strftime("fresh_%Y%m%d_%H%M%S")
        else:
            seed_controls_cache(cache_dir)
        tasks = {**(tasks or {}), **c_tasks}
        recs = list(recs) + c_recs
    user_tasks_given = bool(tasks) and (not controls or any(not str(k).startswith("control:") for k in (tasks or {})))
    judge_model = JUDGE_MODELS.get(judge_model, judge_model)
    tasks, cl_info = ensure_checklists(
        recs, tasks, cache_dir, checklist=checklist, derive=derive_checklists, model=judge_model
    )
    S, info = score_records(recs, tasks, cache_dir, workers=workers, model=judge_model)
    info["checklists"] = cl_info
    info["judge_model"] = judge_model
    if controls:  # user tasks count as 'supplied' only if the caller gave some beyond the control tasks
        info["tasks_without_designer_targets"] = [
            t for t in info["tasks_without_designer_targets"] if not str(t).startswith("control:")
        ]
    res = build_result(S, info, tasks_given=user_tasks_given, expected=expected)
    if res.get("controls"):
        res["controls"]["fresh_rejudge"] = bool(controls_fresh)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rank elicitation skill from existing transcripts (see module docstring for formats)."
    )
    ap.add_argument("input")
    ap.add_argument("--tasks", default=None, help="tasks.yaml (trial/SCHEMA.md) with designer targets per task_id")
    ap.add_argument(
        "--checklist",
        default=None,
        help="checklist file: one item per line (applies to every task) or JSON {task_id: [items]}; used for tasks without designer targets",
    )
    ap.add_argument(
        "--judge-model",
        default=SONNET,
        help="claude-sonnet-5 (default; the model every reference number, control anchor and coder-agreement check was run with) or claude-opus-5",
    )
    ap.add_argument(
        "--no-derive",
        action="store_true",
        help="do not write a checklist for tasks that lack one (old behaviour: the judge writes its own list inside every call)",
    )
    ap.add_argument("--out", default=None, help="output directory (default results/rank_<input stem>)")
    ap.add_argument("--cache", default=None, help="judge cache directory (default <out>/judge_cache)")
    ap.add_argument("--format", default="auto", choices=["auto", "schema", "sharegpt", "openai", "csv", "txtdir"])
    ap.add_argument("--id-field", default=None, help="object field holding the participant id (openai/sharegpt inputs)")
    ap.add_argument("--participant-id", default=None, help="assign every session in INPUT to this one person")
    ap.add_argument("--max-sessions", type=int, default=None, help="score only the first N sessions (input order)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--controls-fresh",
        action="store_true",
        help="with --controls: re-judge the anchors now (12 new judge calls) instead of replaying controls/judge_cache.json; the only mode that detects judge sampling drift or a silent backend change",
    )
    ap.add_argument(
        "--controls",
        action="store_true",
        help="also score the control (anchor) transcripts in controls/ and report whether their reference scores are reproduced",
    )
    a = ap.parse_args(argv)
    recs, detected = load_input(a.input, a.format, a.id_field, a.participant_id)
    if a.max_sessions:
        recs = recs[: a.max_sessions]
    if not recs:
        sys.exit("no sessions parsed from input")
    tasks = yaml.safe_load(open(a.tasks)) if a.tasks else None
    out = pathlib.Path(a.out) if a.out else ROOT / "results" / f"rank_{pathlib.Path(a.input).stem}"
    cache = pathlib.Path(a.cache) if a.cache else out / "judge_cache"
    print(
        f"parsed {len(recs)} sessions ({detected}) from {a.input}; {len({r['participant_id'] for r in recs})} persons; judging (cache {cache}) ..."
    )
    cl = parse_checklist_text(open(a.checklist).read()) if a.checklist else None
    res = run(
        recs,
        tasks,
        cache,
        workers=a.workers,
        controls=(a.controls or a.controls_fresh),
        controls_fresh=a.controls_fresh,
        checklist=cl,
        derive_checklists=not a.no_derive,
        judge_model=a.judge_model,
    )
    write_outputs(res, out, a.input)
    s, rel = res["summary"], res["reliability"]
    print(
        f"scored {s['n_sessions_scored']}/{s['n_sessions_input']} sessions, {s['n_persons']} persons; new judge calls {s['new_judge_calls']}; judge failures {s['judge_failures']}"
    )
    for tid, c in (s.get("checklists") or {}).items():
        print(f"checklist for task {tid!r} ({c['source']}): " + "; ".join(f"{k} {v}" for k, v in c["items"].items()))
    if s["overall_distribution"]:
        c = s["overall_distribution"]
        print(f"per-person overall: mean {_f(c['mean'])} sd {_f(c['sd'])} range {_f(c['min'])}-{_f(c['max'])}")
    print("reliability:", rel["message"])
    P = res["_P"]
    print(
        "top 5:",
        ", ".join(
            f"{r.participant_id} {_f(r.overall)} (n={r.n_sessions}, {r.n_observed_mean} of 5 observed)"
            for _, r in P.head(5).iterrows()
        ),
    )
    print("NOTE:", CAVEAT.split(". ")[1] + ".", "See", out / "ranking.md")
    print("wrote", out / "ranking.csv", out / "sessions.csv", out / "ranking.md", out / "ranking.json")
    return res


if __name__ == "__main__":
    main()
