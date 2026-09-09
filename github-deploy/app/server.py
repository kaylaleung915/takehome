"""FastAPI server. Hidden components + LLM credential live only here.
POST /api/start {item_id}            -> {session_id, item(public), status}
POST /api/turn  {session_id, message}-> {reply, status}          (turn cap 12; 1080 s = 18 min PARTICIPANT time (backstop; 12 messages binds), clock paused while model generates; 1500 s = 25 min hard wall from /start; defaults WALL and HARD_WALL below, env-overridable; SPEC A3 as amended A3.1, A3.2)
POST /api/submit{session_id, text}   -> {score, reveal, components(now disclosed), baselines}
GET  /api/items, /api/config, /api/byok_items (hidden components for bring-your-own-key mode; off with EST_SERVE_BYOK_ITEMS=0),
     /api/results (precomputed table/baselines/gates/openai numbers), /api/health
POST /api/score_transcripts (app/rank_api.py; GET /api/score_transcripts/limits) -> per-session judge scores and ranking.
     Sends transcript text to the model API: do not point it at chemical or biological trial transcripts; run
     analyze_trial.py or analyze_estimands.py where those transcripts live (trial/SCHEMA.md section 0 item 13).
Static page at / .
"""
from __future__ import annotations
import json, os, pathlib, time, uuid, threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from est.items import load_item, list_items, public_view
from est.controller import Session
from est.scorer import score
from est.llm import backend_name, SONNET, HAIKU
from starlette.middleware.base import BaseHTTPMiddleware

TURN_CAP = int(os.environ.get("EST_TURN_CAP", "12"))
WALL = int(os.environ.get("EST_WALL_SECONDS", "1080"))          # participant-time budget for the chat phase (SPEC amendment A3, 2026-09-08)
HARD_WALL = int(os.environ.get("EST_HARD_WALL_SECONDS", "1500"))  # absolute backstop from /start
VERSION = "1.5.3"
RUNS_HUMAN = pathlib.Path(os.environ.get("EST_RUNS_DIR", str(ROOT / "runs" / "human")))  # on Modal this is a persistent Volume
ATTEMPTS_F = RUNS_HUMAN / "attempts.json"          # retake registry keyed on participant id
MAX_SESSIONS = int(os.environ.get("EST_MAX_SESSIONS", "200"))
app = FastAPI(title="Elicitation Skill Test")
try:                                   # transcript ranking (rank_transcripts.py); optional so the chat page survives an import error
    from app.rank_api import router as rank_router
    app.include_router(rank_router); RANK_OK = True
except Exception as e:                 # noqa
    RANK_OK = False; RANK_ERR = repr(e)[:200]


class NoStore(BaseHTTPMiddleware):
    """The page and precomputed bundle change with each deploy; a browser-cached v1 bundle listed retired items and
    /api/start then returned 'unknown item' (owner report 2026-09-08). Never let the browser cache them."""
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        p = request.url.path
        if p == "/" or p.startswith("/static") or p.startswith("/api"):
            resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp
app.add_middleware(NoStore)


def _attempts() -> dict:
    try:
        return json.load(open(ATTEMPTS_F))
    except Exception:
        return {}

def _record_attempt(pid: str, item_id: str, mode: str) -> int:
    with LOCK:
        a = _attempts(); lst = a.setdefault(pid, [])
        lst.append({"item": item_id, "mode": mode, "ts": time.strftime("%F %T")})
        try:
            ATTEMPTS_F.parent.mkdir(parents=True, exist_ok=True); json.dump(a, open(ATTEMPTS_F, "w"), indent=1)
        except Exception:
            pass
        return sum(1 for x in lst if x["item"] == item_id)
SESS: dict[str, Session] = {}
LOCK = threading.Lock()
DONE_DIR = RUNS_HUMAN; DONE_DIR.mkdir(parents=True, exist_ok=True)
LIVE_DIR = RUNS_HUMAN / "live_sessions"; LIVE_DIR.mkdir(parents=True, exist_ok=True)
# Live-session persistence (owner report 2026-09-08, "[error: unknown session]" mid-chat): sessions lived only in this
# process's memory, so a redeploy or container restart dropped every open chat. Each session is now pickled to the runs
# volume after /start and every /turn, and reloaded on a cache miss. On Modal the volume is committed after each write so a
# replacement container sees it; locally LIVE_DIR is just a folder.
_VOL = None
def _vol():
    global _VOL
    if _VOL is None and os.environ.get("MODAL_TASK_ID"):
        try:
            import modal; _VOL = modal.Volume.from_name(os.environ.get("EST_MODAL_VOLUME", "est-human-runs"))
        except Exception:
            _VOL = False
    return _VOL or None

def _persist(sid: str, s: Session):
    try:
        import pickle; tmp = LIVE_DIR / f"{sid}.pkl.tmp"
        with open(tmp, "wb") as f: pickle.dump(s, f)
        os.replace(tmp, LIVE_DIR / f"{sid}.pkl")
        v = _vol()
        if v: v.commit()
    except Exception:
        pass

def _forget(sid: str):
    try:
        (LIVE_DIR / f"{sid}.pkl").unlink(missing_ok=True)
        v = _vol()
        if v: v.commit()
    except Exception:
        pass

def _get_session(sid: str):
    s = SESS.get(sid)
    if s is not None: return s
    if not sid or not all(c in "0123456789abcdef" for c in sid): return None
    try:
        v = _vol()
        if v:
            try: v.reload()
            except Exception: pass
        f = LIVE_DIR / f"{sid}.pkl"
        if not f.exists(): return None
        import pickle
        with open(f, "rb") as fh: s = pickle.load(fh)
        with LOCK: SESS[sid] = s
        return s
    except Exception:
        return None


def _results():
    out = {"backend": backend_name(), "turn_cap": TURN_CAP, "wall_seconds": WALL}
    for name in ["baselines.json", "openai2024.json", "g2.json"]:
        p = ROOT / "results" / name
        if name == "baselines.json" and (ROOT / "results" / "g1_run3" / "baselines.json").exists(): p = ROOT / "results" / "g1_run3" / "baselines.json"  # G1 run 3 (A2) preferred; run 2 stays in results/baselines.json
        out[name.split(".")[0]] = json.load(open(p)) if p.exists() else None
    for name in ["table.md", "openai2024_numbers.md"]:
        p = ROOT / "results" / name
        out[name.replace(".", "_")] = p.read_text() if p.exists() else None
    return out


class StartReq(BaseModel):
    item_id: str
    participant_id: str | None = None
    mode: str | None = "practice"   # "practice" | "scored"; scored attempts beyond the first on a level are flagged, not blocked
class TurnReq(BaseModel):
    session_id: str
    message: str
class SubmitReq(BaseModel):
    session_id: str
    text: str
    participant_id: str | None = None


@app.get("/api/health")
def health():
    import shutil
    return {"ok": True, "backend": backend_name(), "sessions": len(SESS),
            "claude_cli_present": shutil.which("claude") is not None,
            "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EST_ANTHROPIC_API_KEY")),
            "oauth_token_set": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
            "turn_cap": TURN_CAP, "wall_seconds": WALL, "hard_wall_seconds": HARD_WALL, "byok_items_served": SERVE_BYOK_ITEMS, "version": VERSION}

@app.get("/api/config")
def config():
    """Public test configuration, including which models play which role (owner request 2026-09-08)."""
    return {"version": VERSION, "transcript_ranking": RANK_OK, "turn_cap": TURN_CAP,
            "chat_participant_time_s": WALL, "hard_wall_s": HARD_WALL,
            "clock": "participant time only: the chat clock pauses while the assistant is generating (SPEC amendment A3)",
            "answer_phase": "separate and untimed (about 5 minutes suggested, please stop by 10); chat is locked once you submit",
            "models": {"assistant": SONNET, "per_turn_gatekeeper_judge": SONNET, "submission_judge": SONNET,
                       "transcript_session_judge": SONNET, "scripted_synthetic_participants": HAIKU},
            "backend": backend_name(),
            "retake_policy": "every start is logged against the participant id; the reveal and the trial export carry attempt_no for that level; a trial should treat attempt_no>1 on a scored level as practice-contaminated. Enforcement of identity is the trial platform's job (this server cannot know who is at the keyboard)."}

@app.get("/api/items")
def items():
    return [public_view(load_item(i)) for i in list_items()]

SERVE_BYOK_ITEMS = os.environ.get("EST_SERVE_BYOK_ITEMS", "1") != "0"
@app.get("/api/byok_items")
def byok_items():
    """Full item dicts (hidden records included, base64) for bring-your-own-key mode only. Fetched by the page only when
    a BYOK session starts; not part of /static/precomputed.json since v1.3.1 (V5e concern C1). Set EST_SERVE_BYOK_ITEMS=0
    on any deployment used for scored sessions: BYOK then reports itself unavailable and hosted mode is unaffected."""
    if not SERVE_BYOK_ITEMS:
        raise HTTPException(403, "bring-your-own-key mode is disabled on this deployment (EST_SERVE_BYOK_ITEMS=0); use hosted mode or run locally")
    p = ROOT / "app" / "private" / "byok_items.json"
    if not p.exists():
        raise HTTPException(404, "byok_items.json not built; run app/build_static.py")
    return json.loads(p.read_text())

@app.get("/api/results")
def results():
    return _results()

@app.get("/results/openai2024.png")
def chart():
    p = ROOT / "results" / "openai2024.png"
    if not p.exists(): raise HTTPException(404)
    return FileResponse(p)

@app.post("/api/start")
def start(req: StartReq):
    if req.item_id not in list_items(): raise HTTPException(404, "unknown item")
    with LOCK:
        if len(SESS) >= MAX_SESSIONS:
            # drop oldest
            oldest = sorted(SESS.items(), key=lambda kv: kv[1].t0)[0][0]; SESS.pop(oldest)
        sid = uuid.uuid4().hex
        SESS[sid] = Session(load_item(req.item_id), turn_cap=TURN_CAP, wall_seconds=WALL, hard_wall_seconds=HARD_WALL)
    s = SESS[sid]
    pid = (req.participant_id or "").strip()[:40] or None
    s.participant_id = pid; s.mode = (req.mode or "practice")
    s.attempt_no = _record_attempt(pid, req.item_id, s.mode) if pid else None
    prior = None
    if pid:
        prior = [x for x in _attempts().get(pid, [])][:-1]
    _persist(sid, s)
    return {"session_id": sid, "item": public_view(s.item), "status": s.status(), "attempt_no": s.attempt_no,
            "prior_attempts": prior, "models": {"assistant": SONNET, "judges": SONNET}}

@app.post("/api/turn")
def turn(req: TurnReq):
    s = _get_session(req.session_id)
    if s is None: raise HTTPException(404, "unknown session (the server has no record of it; it was started before live-session persistence or has expired). Press Start session to begin again.")
    msg = (req.message or "").strip()[:2000]
    if not msg: raise HTTPException(400, "empty message")
    if not s.can_send():
        return JSONResponse({"error": "message cap or chat-time budget reached, or already submitted; please write and submit your answer", "status": s.status()}, status_code=409)
    try:
        reply = s.turn(msg)
    except Exception as e:
        _persist(req.session_id, s)
        raise HTTPException(502, f"backend error: {str(e)[:200]}")
    _persist(req.session_id, s)
    # client sees only the visible reply and status — never components, judge output, or unlock state
    return {"reply": reply, "status": s.status()}

@app.post("/api/submit")
def submit(req: SubmitReq):
    s = _get_session(req.session_id)
    if s is None: raise HTTPException(404, "unknown session (the server has no record of it). Press Start session to begin again.")
    if s.submitted is not None: raise HTTPException(409, "already submitted")
    s.submit((req.text or "").strip()[:6000])
    rec = s.to_record()
    try:
        sc = score(s.item, rec)
    except Exception as e:
        raise HTTPException(502, f"scoring backend error: {str(e)[:200]}")
    comps = {cid: {"tier": c["tier"], "text": c["text"], **({"specific_requirement": c["specific_requirement"]} if "specific_requirement" in c else {}), **({"planted_error": c["planted_error"]} if "planted_error" in c else {})}
             for cid, c in s.item["components"].items()}
    base = None
    p = ROOT / "results" / "g1_run3" / "baselines.json"
    if not p.exists(): p = ROOT / "results" / "baselines.json"  # reveal baselines: G1 run 3 (state-machine fixtures) when present, else run 2
    if p.exists():
        b = json.load(open(p)); base = {"item": b.get(s.item["id"]), "pooled": b.get("_pooled")}
    out = {"score": sc["subscales"], "reveal": sc["reveal"], "components": comps, "baselines": base,
           "per_turn": [{"turn": t["turn"], "participant": (t.get("participant") or "")[:200], "levels": t["judge"]["levels"], "votes": t["judge"].get("votes"), "challenges_error": t["judge"]["challenges_error"], "released": t["released"]} for t in rec["log"]],
           "status": s.status()}
    try:
        rec.update({"policy": "HUMAN", "score": sc, "ts": time.strftime("%F %T"), "participant_id": getattr(s, "participant_id", None),
                    "mode": getattr(s, "mode", None), "attempt_no": getattr(s, "attempt_no", None), "status_at_submit": s.status()})
        json.dump(rec, open(DONE_DIR / f"{s.item['id']}__{req.session_id[:8]}.json", "w"), indent=1)
        _persist(req.session_id, s)
        # same record in the post-trial pipeline schema (trial/SCHEMA.md), participant_id supplied by client or session prefix
        from est.export import record_to_transcript
        with open(DONE_DIR / "transcripts.jsonl", "a") as f:
            tr = record_to_transcript(rec, (req.participant_id or getattr(s, "participant_id", None) or req.session_id[:8]), -1)
            tr.update({"attempt_no": getattr(s, "attempt_no", None), "mode": getattr(s, "mode", None)})
            f.write(json.dumps(tr) + "\n")
    except Exception:
        pass
    out["export"] = {"schema": "trial/SCHEMA.md", "participant_id": req.participant_id or getattr(s, "participant_id", None) or req.session_id[:8],
                     "attempt_no": getattr(s, "attempt_no", None), "mode": getattr(s, "mode", None)}
    return out

STATIC = ROOT / "app" / "static"
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
