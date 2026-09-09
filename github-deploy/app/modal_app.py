"""Modal deployment. `modal deploy -e <environment> app/modal_app.py` -> public URL.
Deployed as the separate app `est-demo` (2026-09-08) so the earlier `elicitation-skill-test` app stays up unchanged.
Hosted-mode LLM credential comes from Modal secret `anthropic-est` containing ONE of:
  CLAUDE_CODE_OAUTH_TOKEN=...   (from `claude setup-token`; uses headless claude CLI in the container)
  ANTHROPIC_API_KEY=...         (Anthropic API; SDK backend)
With neither, the page still serves precomputed results + bring-your-own-key mode; hosted mode returns 502 with guidance.
"""
import modal, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("curl", "ca-certificates", "nodejs", "npm")
         .run_commands("npm install -g @anthropic-ai/claude-code && claude --version")
         .pip_install("fastapi[standard]==0.115.*", "anthropic>=0.40", "pyyaml", "pydantic>=2", "numpy", "pandas", "scipy")
         .env({"EST_BACKEND": "auto", "EST_CONCURRENCY": "4", "PYTHONPATH": "/root/est_app", "EST_RUNS_DIR": "/root/est_runs", "EST_MODAL_VOLUME": "est-demo-runs"})
         .add_local_dir(str(ROOT / "est"), "/root/est_app/est")
         .add_local_dir(str(ROOT / "app"), "/root/est_app/app")
         .add_local_dir(str(ROOT / "items"), "/root/est_app/items")
         .add_local_dir(str(ROOT / "results"), "/root/est_app/results", ignore=lambda pth: not str(pth).endswith((".json", ".md", ".png")) or any(seg in str(pth) for seg in ("weidmann2025", "smoke_preflight", "rank_demo", "rank_fixture")))  # server reads only top-level table/baselines/g2/openai files
         .add_local_dir(str(ROOT / "trial"), "/root/est_app/trial")
         .add_local_dir(str(ROOT / "controls"), "/root/est_app/controls")
         .add_local_file(str(ROOT / "rank_transcripts.py"), "/root/est_app/rank_transcripts.py")
         .add_local_file(str(ROOT / "analyze_trial.py"), "/root/est_app/analyze_trial.py"))
app = modal.App("est-demo", image=image)
runs_vol = modal.Volume.from_name("est-demo-runs", create_if_missing=True)  # persists session records + retake registry across container restarts (fresh volume for this app)

@app.function(secrets=[modal.Secret.from_name("anthropic-est")], volumes={"/root/est_runs": runs_vol}, timeout=1800, scaledown_window=600, max_containers=1)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def web():
    import sys; sys.path.insert(0, "/root/est_app")
    from app.server import app as fastapi_app
    return fastapi_app
