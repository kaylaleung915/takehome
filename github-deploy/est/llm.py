"""LLM backend abstraction.
Backends (EST_BACKEND env): cli (default; headless `claude -p`, OAuth), sdk (Anthropic API key),
vertex (AnthropicVertex; needs EST_VERTEX_PROJECT, EST_VERTEX_REGION).
complete(system, messages, model, max_tokens) -> str. messages = [{"role":"user"|"assistant","content":str}, ...]
"""
from __future__ import annotations
import json, os, re, subprocess, time, threading

SONNET = os.environ.get("EST_MODEL_MAIN", "claude-sonnet-5")
HAIKU = os.environ.get("EST_MODEL_PARTICIPANT", "claude-haiku-4-5-20251001")
_VERTEX_IDS = {"claude-sonnet-5": "claude-sonnet-5", "claude-haiku-4-5-20251001": "claude-haiku-4-5@20251001"}
_lock = threading.Semaphore(int(os.environ.get("EST_CONCURRENCY", "6")))


def _serialize(messages):
    out = []
    for m in messages:
        who = "USER" if m["role"] == "user" else "ASSISTANT"
        out.append(f"### {who}\n{m['content'].strip()}")
    out.append("### ASSISTANT\n(write ONLY the assistant's next reply; no preamble, no role label)")
    return "\n\n".join(out)


def _cli(system, messages, model, max_tokens):
    prompt = _serialize(messages) if len(messages) > 1 else messages[0]["content"]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    # v1.4.3: the prompt goes in on stdin, not argv, so long transcripts are not capped by the 128 KiB per-argument exec limit.
    cmd = ["claude", "-p", "--model", model, "--output-format", "json", "--system-prompt", system, "--tools", ""]
    tmo = 240 + len(prompt) // 1500                      # roughly +1 s per 1,500 characters beyond the old flat 240 s
    for attempt in range(3):
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd="/tmp", timeout=tmo, input=prompt)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and '"result"' in line:
                j = json.loads(line)
                if not j.get("is_error"):
                    return j.get("result", "")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"cli backend failed: {r.stdout[:300]} {r.stderr[:300]}")


_sdk_client = None
def _sdk(system, messages, model, max_tokens):
    global _sdk_client
    import anthropic
    if _sdk_client is None:
        key = os.environ.get("EST_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        _sdk_client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    r = _sdk_client.messages.create(model=model, max_tokens=max_tokens, system=system, messages=messages)
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


_vx_client = None
def _vertex(system, messages, model, max_tokens):
    global _vx_client
    from anthropic import AnthropicVertex
    if _vx_client is None:
        _vx_client = AnthropicVertex(project_id=os.environ["EST_VERTEX_PROJECT"], region=os.environ.get("EST_VERTEX_REGION", "us-east5"))
    r = _vx_client.messages.create(model=_VERTEX_IDS.get(model, model), max_tokens=max_tokens, system=system, messages=messages)
    return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


def backend_name():
    b = os.environ.get("EST_BACKEND", "cli")
    if b != "auto":
        return b
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "cli"
    if os.environ.get("EST_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return "sdk"
    if os.environ.get("EST_VERTEX_PROJECT"):
        return "vertex"
    return "none"


def _none(*a, **k):
    raise RuntimeError("no LLM credential configured on this server (set Modal secret 'anthropic-est'); use bring-your-own-key mode or run locally")


def complete(system: str, messages: list, model: str = SONNET, max_tokens: int = 1024) -> str:
    b = backend_name()
    fn = {"cli": _cli, "sdk": _sdk, "vertex": _vertex, "none": _none}[b]
    with _lock:
        for attempt in range(3):
            try:
                return fn(system, messages, model, max_tokens)
            except Exception as e:  # noqa
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))


def complete_json(system: str, messages: list, model: str = SONNET, max_tokens: int = 1024) -> dict:
    txt = complete(system + "\n\nRespond with a single JSON object only. No prose, no code fences.", messages, model, max_tokens)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError(f"no JSON in: {txt[:200]}")
    return json.loads(m.group(0))
