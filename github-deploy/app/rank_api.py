"""APIRouter: score and rank elicitation skill from pasted / uploaded EXISTING transcripts.
POST /api/score_transcripts
  body: {"transcripts": [trial/SCHEMA.md records...]}                        (already-normalised sessions)
     or {"text": "<pasted JSONL / JSON / CSV / 'User:'/'Assistant:' text>", "participant_id": optional}
     or {"files": [{"name": "p017__s1.txt", "text": "..."}, ...], "participant_id": optional}   (v1.4.2: several uploaded files;
         each file is parsed on its own, format from its extension; for .txt files the participant id is the file stem before "__";
         JSON/JSONL/CSV records keep their own participant_id (id-less JSON records become <stem>_000, <stem>_001, ... as in the paste path);
         "text" and "files" may be sent together and are pooled before the limits are applied)
     optional in any: "tasks": {task_id: {prompt, targets{...}}} in the tasks.yaml shape
     Agent-session exports ({export_version, root_frame_id, frames:[...]}) are accepted (v1.4.3): the root frame's typed user turns and
         assistant prose are kept; tool calls, tool results, thinking, images, harness notices and sub-agent frames are dropped.
  limits (v1.4.3): <= 24 files, <= 24 sessions, <= 300,000 characters of conversation per session and <= 2,000,000 pooled AFTER parsing,
          <= 40,000,000 characters of raw upload per request (413); 30 requests/hour per process (429)
  returns: {"sessions": [...], "persons": [...], "reliability": {...}, "summary": {...}, "caveat": "..."}
Mount with: from app.rank_api import router; app.include_router(router)
Same scoring as rank_transcripts.py / analyze_trial.py; judge cache under runs/rank_cache. Never returns server config.
"""
from __future__ import annotations
import json, os, pathlib, sys, threading, time
from collections import deque
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from rank_transcripts import parse_text_blob, _finalise, total_chars, run as rank_run, CAVEAT, _looks_like_export, parse_checklist_text, JUDGE_MODELS

MAX_SESSIONS = 24
MAX_CHARS = 2_000_000          # pooled conversation characters AFTER parsing (tool output, images, sub-agents already dropped)
MAX_SESSION_CHARS = 300_000    # one session as rendered for the judge; about 75k tokens, inside the judge model's context
MAX_RAW_CHARS = 40_000_000     # raw request text before parsing; a memory backstop, not a scoring limit
MAX_FILES = 24
RATE_PER_HOUR = 30
CACHE_DIR = pathlib.Path(os.environ["EST_RUNS_DIR"]).parent / "rank_cache" if os.environ.get("EST_RUNS_DIR") else ROOT / "runs" / "rank_cache"
SAMPLE_CACHE = ROOT / "app" / "static" / "samples" / "judge_cache"   # judge outputs for the page's bundled sample transcripts, so the demo click needs no new judge calls


def _seed_sample_cache() -> int:
    """Copy the shipped judge outputs for the bundled samples into CACHE_DIR (keys hash transcript, checklist, prompt and model,
    so they are only ever hit by the identical request). A fresh container otherwise re-judges the six sample sessions."""
    n = 0
    try:
        from est.transcripts import bundled_entries
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for name, out in bundled_entries(SAMPLE_CACHE).items():   # shipped as one file, samples/judge_cache.json
            if not (CACHE_DIR / name).exists():
                (CACHE_DIR / name).write_text(json.dumps(out, indent=1)); n += 1
        if SAMPLE_CACHE.is_dir():
            for f in SAMPLE_CACHE.glob("*.json"):
                if not (CACHE_DIR / f.name).exists():
                    (CACHE_DIR / f.name).write_bytes(f.read_bytes()); n += 1
    except Exception:
        pass
    return n


_seed_sample_cache()
_hits: deque = deque()
_rl_lock = threading.Lock()
_score_lock = threading.Semaphore(2)          # at most two scoring jobs at once per process

router = APIRouter()


def _controls_meta():
    try:
        from rank_transcripts import load_controls
        _, _, e = load_controls()
        return {"available": True, "version": e.get("version"), "n_sessions": e.get("n_sessions"), "n_chars": e.get("n_chars"),
                "persons": [{"participant_id": k, "kind": v.get("kind"), "label": v.get("label"),
                             "reference_composite": (v.get("ground_truth") or v.get("judge_reference") or {}).get("composite")} for k, v in e["persons"].items()]}
    except Exception:
        return {"available": False}


class UploadedFile(BaseModel):
    name: str | None = None
    text: str = ""


class ScoreReq(BaseModel):
    transcripts: list[dict] | None = None
    text: str | None = None
    files: list[UploadedFile] | None = None
    participant_id: str | None = None
    judge_model: str | None = None        # claude-sonnet-5 (default, reference scale) or claude-opus-5
    tasks: dict | None = None
    checklist: str | None = None          # one item per line (all tasks) or JSON {task_id: [items]}; replaces tool-written checklists
    include_controls: bool | None = True


def _rate_ok() -> bool:
    now = time.time()
    with _rl_lock:
        while _hits and now - _hits[0] > 3600: _hits.popleft()
        if len(_hits) >= RATE_PER_HOUR: return False
        _hits.append(now); return True


@router.get("/api/score_transcripts/limits")
def limits():
    return {"max_sessions": MAX_SESSIONS, "max_chars": MAX_CHARS, "max_session_chars": MAX_SESSION_CHARS, "max_raw_chars": MAX_RAW_CHARS, "max_files": MAX_FILES, "rate_per_hour": RATE_PER_HOUR, "caveat": CAVEAT,
            "controls": _controls_meta(),
            "judge_model": "claude-sonnet-5 (default; all reference numbers, control anchors and the coder-agreement check used it) or claude-opus-5 (control anchors are then re-judged rather than replayed, and scores are not on the same scale as the Sonnet references)",
            "checklist": "optional: one item per line (applies to every task) or JSON {task_id: [items]}; when absent the tool writes one checklist per task (one extra model call per task) and returns it in summary.checklists",
            "formats": ["schema JSONL (trial/SCHEMA.md)", "OpenAI-style {messages:[{role,content}]} JSON/JSONL", "ShareGPT {conversations:[{from,value}]}",
                        "CSV participant_id,session_idx,role,content", "plain text with 'User:' / 'Assistant:' turns ('===' line between sessions)",
                        "agent-session export JSON {export_version, root_frame_id, frames:[{messages:[...]}]} (root frame only; tool calls, tool results, thinking, images dropped)"]}


@router.post("/api/score_transcripts")
def score_transcripts(req: ScoreReq):
    files = [f for f in (req.files or []) if (f.text or "").strip()]
    if not req.transcripts and not (req.text and req.text.strip()) and not files:
        raise HTTPException(400, "send 'transcripts' (list of schema records), 'text' (pasted transcripts) or 'files' ([{name, text}])")
    if req.transcripts and (files or (req.text and req.text.strip())):
        raise HTTPException(400, "send 'transcripts' alone; it cannot be combined with 'text' or 'files' in one request")
    if req.files is not None and len(req.files) > MAX_FILES:
        raise HTTPException(413, f"too many files: {len(req.files)}; the limit is {MAX_FILES} per request (and {MAX_SESSIONS} sessions in total). Run rank_transcripts.py locally on a directory for larger sets.")
    # size checks BEFORE any parsing work beyond length
    try:   # V59b N16: pathological nesting in 'transcripts' content must be a 400, not a 500, on any Python version
        tasks_len = len(json.dumps(req.tasks, default=str)) if req.tasks is not None else 0   # V59c SF2: inside the try so deep nesting is a 400
        pid_len = len(req.participant_id or "")
        raw_len = pid_len + len(req.checklist or "") + len(req.text or "") + sum(len(f.text or "") + len(f.name or "") for f in (req.files or [])) + sum(len(str(m.get("content", ""))) for r in (req.transcripts or []) if isinstance(r, dict) for m in (r.get("messages") or []) if isinstance(m, dict))
    except (RecursionError, TypeError, ValueError) as e:
        raise HTTPException(400, f"could not read the request body ({type(e).__name__})")
    if pid_len > 64:                                                                      # V59c SF3: participant_id capped, was echoed uncapped via force_pid
        raise HTTPException(400, "participant_id too long (limit 64 characters)")
    if tasks_len > 20_000:      # V18: tasks payload was unbounded
        raise HTTPException(413, "tasks payload too large (limit 20,000 characters of JSON)")
    if raw_len > MAX_RAW_CHARS:
        raise HTTPException(413, f"upload too large: {raw_len:,} characters of raw text; the limit is {MAX_RAW_CHARS:,} per request. Send fewer files per request, or run rank_transcripts.py locally.")
    if req.transcripts is not None and len(req.transcripts) > MAX_SESSIONS:
        raise HTTPException(413, f"too many sessions: {len(req.transcripts)}; the limit is {MAX_SESSIONS} per request. Run rank_transcripts.py locally for larger sets.")
    pid_default = (req.participant_id or "").strip()[:64] or "pasted"
    try:
        if req.transcripts:
            recs = []
            from rank_transcripts import _obj_to_record
            for i, o in enumerate(req.transcripts):
                if not isinstance(o, dict): continue
                r = _obj_to_record(o, pid_default if len(req.transcripts) == 1 or req.participant_id else f"{pid_default}_{i:03d}", i, None)
                if r: recs.append(r)
            recs = _finalise(recs); detected = "schema"
        else:
            recs, dets = [], []
            if req.text and req.text.strip():
                rs, det = parse_text_blob(req.text, default_pid=pid_default, force_pid=(pid_default if req.participant_id and req.participant_id.strip() else None))
                recs += rs; dets.append(det)
            for i, f in enumerate(files):
                stem = pathlib.Path((f.name or f"file{i:02d}").replace("\\", "/")).name
                suffix = pathlib.Path(stem).suffix.lower(); stem = pathlib.Path(stem).stem[:64] or f"file{i:02d}"
                fpid = stem.split("__")[0] or stem
                eff = "csv" if suffix == ".csv" else "txt" if (suffix == ".txt" and not _looks_like_export(f.text)) else "auto"   # V59 N2: an export saved as .txt is still an export
                rs, det = parse_text_blob(f.text, default_pid=fpid, fmt=eff, force_pid=(pid_default if req.participant_id and req.participant_id.strip() else None))
                if det == "txt":
                    for r in rs: r["session_idx"] = None        # .txt files carry no session index: number sessions per person in file order (avoids idx collisions across files)
                for r in rs: r["_file"] = stem + suffix
                recs += rs; dets.append(det)
            if files:                                            # pooled sources: avoid (participant_id, session_idx) collisions (V58 N1)
                by_pid = {}
                for r in recs: by_pid.setdefault(str(r.get("participant_id") or "anon"), []).append(r)
                for pid_k, rs_k in by_pid.items():
                    idxs = [r.get("session_idx") for r in rs_k]
                    explicit = [i for i in idxs if i is not None]
                    if req.participant_id or len(set(map(str, explicit))) < len(explicit) or (explicit and len(explicit) < len(idxs)):
                        for r in rs_k: r["session_idx"] = None   # _finalise then numbers 0..n-1 in pooled order
            recs = _finalise(recs)
            detected = dets[0] if len(set(dets)) == 1 else ("mixed: " + ", ".join(sorted(set(dets)))) if dets else "unknown"
    except ValueError as e:
        msg = str(e); msg = msg.split("; got")[0] if "; got" in msg else msg     # V58 N4: do not echo an uploaded file's first row back
        raise HTTPException(400, f"could not parse transcripts: {msg[:200]}")
    except (TypeError, AttributeError, KeyError, IndexError, RecursionError):   # V59 S3: malformed structures are a 400, not a bare 500; no input echoed
        raise HTTPException(400, "could not parse transcripts: the JSON is well formed but not in an accepted shape (see /api/score_transcripts/limits 'formats').")
    if not recs:
        raise HTTPException(400, "no sessions with at least one typed user turn were found. Accepted: schema JSONL, OpenAI-style messages JSON, ShareGPT JSON, CSV (participant_id,session_idx,role,content), 'User:'/'Assistant:' text, or an agent-session export JSON with a frames list (root frame must contain at least one typed user message).")
    if len(recs) > MAX_SESSIONS:
        raise HTTPException(413, f"too many sessions: {len(recs)} parsed; the limit is {MAX_SESSIONS} per request. Run rank_transcripts.py locally for larger sets.")
    n_chars = total_chars(recs)
    big = [(r["participant_id"], r["session_idx"], total_chars([r])) for r in recs if total_chars([r]) > MAX_SESSION_CHARS]
    if big:
        desc = "; ".join(f"{p} session {i}: {c:,} characters" for p, i, c in big[:5])
        raise HTTPException(413, f"session too long for one judge call ({desc}); the per-session limit is {MAX_SESSION_CHARS:,} characters of conversation after tool output and attachments are dropped.")
    if n_chars > MAX_CHARS:
        raise HTTPException(413, f"too much conversation text: {n_chars:,} characters across {len(recs)} sessions after parsing; the limit is {MAX_CHARS:,} per request. Split the upload across requests.")
    tasks = req.tasks if isinstance(req.tasks, dict) else None
    if req.checklist and len(req.checklist) > 20_000:                      # V60 S1: length before parse
        raise HTTPException(413, "checklist too long (limit 20,000 characters)")
    try:
        checklist = parse_checklist_text(req.checklist) if (req.checklist and req.checklist.strip()) else None
    except (ValueError, TypeError, RecursionError) as e:
        raise HTTPException(400, f"could not read the checklist: {type(e).__name__} {str(e)[:200]}")
    jm = (req.judge_model or "claude-sonnet-5").strip()
    if jm not in JUDGE_MODELS:
        raise HTTPException(400, f"judge_model must be one of {sorted(set(JUDGE_MODELS.values()))}")
    jm = JUDGE_MODELS[jm]
    if not _rate_ok():                     # V18: count only requests that passed validation against the hourly limit
        raise HTTPException(429, f"rate limit: at most {RATE_PER_HOUR} scoring requests per hour on this server; try again later or run rank_transcripts.py locally.")
    if not _score_lock.acquire(timeout=5):
        raise HTTPException(429, "server is busy scoring other transcripts; retry in a minute")
    try:
        res = rank_run(recs, tasks, CACHE_DIR, workers=3, controls=bool(req.include_controls), checklist=checklist, judge_model=jm)
    except Exception:
        # never echo backend / credential details
        raise HTTPException(502, "the transcript judge backend failed for this request; no scores were produced. Try again, or run rank_transcripts.py locally.")
    finally:
        _score_lock.release()
    s = res["summary"]
    if s["n_sessions_scored"] == 0:
        raise HTTPException(502, "the transcript judge returned no usable output for any session")
    sessions = [{k: v for k, v in r.items() if k not in ("transcript_hash",)} for r in res["sessions"]]
    return {"detected_format": detected, "n_sessions": len(recs), "n_chars": n_chars, "n_files": len(files),
            "sessions": sessions, "persons": res["persons"], "reliability": res["reliability"], "controls": res.get("controls"),
            "summary": {k: s.get(k) for k in ("n_control_persons", "n_control_sessions", "n_sessions_input", "n_sessions_scored", "n_unique_transcripts", "n_persons", "new_judge_calls", "judge_failures", "tasks_yaml_supplied", "tasks_without_designer_targets", "checklists", "checklist_failures", "overall_distribution", "judge_model", "composite_distribution")},
            "caveat": CAVEAT}
