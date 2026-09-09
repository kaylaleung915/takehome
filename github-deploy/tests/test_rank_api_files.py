"""POST /api/score_transcripts with several uploaded files (v1.4.2). Judge is stubbed: no model calls.
Run: .venv/bin/python tests/test_rank_api_files.py   (plain script; also collects under pytest if installed)."""
import json
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import app.rank_api as ra
from fastapi import FastAPI
from fastapi.testclient import TestClient

FX = ROOT / "tests" / "fixtures"
CALLS = {}


def _fake_run(recs, tasks, cache_dir, workers=3, controls=True, **kw):
    CALLS["recs"] = recs; CALLS["kw"] = kw
    persons = {}
    for r in recs: persons.setdefault(r["participant_id"], []).append(r)
    return {"sessions": [{"participant_id": r["participant_id"], "session_idx": r["session_idx"], "task_id": r["task_id"], "composite": 0.5, "transcript_hash": "x"} for r in recs],
            "persons": [{"rank": i + 1, "participant_id": p, "n_sessions": len(v), "composite": 0.5} for i, (p, v) in enumerate(persons.items())],
            "reliability": {"message": "stub"}, "controls": None,
            "summary": {"n_sessions_input": len(recs), "n_sessions_scored": len(recs), "n_unique_transcripts": len({str(r["messages"]) for r in recs}), "n_persons": len(persons), "new_judge_calls": 0, "judge_failures": 0}}


def _client():
    ra.rank_run = _fake_run
    ra._rate_ok = lambda: True
    app = FastAPI(); app.include_router(ra.router)
    return TestClient(app)


try:
    import pytest

    @pytest.fixture()
    def client():
        return _client()
except ImportError:
    pass


def _txt_files():
    return [{"name": f.name, "text": f.read_text()} for f in sorted((FX / "txtdir").glob("*.txt"))]


def test_mixed_files_pooled(client):
    files = _txt_files() + [{"name": "openai_2sessions.jsonl", "text": (FX / "openai_2sessions.jsonl").read_text()},
                            {"name": "csv_2sessions.csv", "text": (FX / "csv_2sessions.csv").read_text()}]
    r = client.post("/api/score_transcripts", json={"files": files, "include_controls": False}); j = r.json()
    assert r.status_code == 200 and j["n_files"] == 4 and j["n_sessions"] == 6
    assert j["detected_format"].startswith("mixed")
    pids = sorted((x["participant_id"], x["session_idx"]) for x in CALLS["recs"])
    assert ("carol", 0) in pids and ("dave", 0) in pids          # .txt stem before "__" is the participant id
    assert len(set(pids)) == len(pids)                             # no (person, session) collisions


def test_files_plus_text_with_forced_pid(client):
    r = client.post("/api/score_transcripts", json={"files": _txt_files(), "text": "User: hi\nAssistant: hello\nUser: more", "participant_id": "p9", "include_controls": False})
    assert r.status_code == 200
    assert sorted((x["participant_id"], x["session_idx"]) for x in CALLS["recs"]) == [("p9", 0), ("p9", 1), ("p9", 2)]


def test_same_person_two_txt_files(client):
    r = client.post("/api/score_transcripts", json={"files": [{"name": "amy__a.txt", "text": "User: q1\nAssistant: r"}, {"name": "amy__b.txt", "text": "User: q2\nAssistant: r"}], "include_controls": False})
    assert r.status_code == 200
    assert sorted((x["participant_id"], x["session_idx"]) for x in CALLS["recs"]) == [("amy", 0), ("amy", 1)]


def test_limits(client):
    assert client.post("/api/score_transcripts", json={"files": [{"name": f"a{i}.txt", "text": "User: x"} for i in range(25)]}).status_code == 413   # > MAX_FILES
    assert client.post("/api/score_transcripts", json={"files": [{"name": "a.txt", "text": "  "}]}).status_code == 400                                # nothing usable
    assert client.post("/api/score_transcripts", json={"files": [{"name": f"p{i}__s.txt", "text": "User: x\nAssistant: y"} for i in range(13)]}).status_code == 200  # v1.4.3: 13 sessions now fine
    assert client.post("/api/score_transcripts", json={"text": "\n===\n".join("User: x\nAssistant: y" for _ in range(25))}).status_code == 413  # > 24 sessions
    assert client.post("/api/score_transcripts", json={"files": [{"name": "a.txt", "text": "User: " + "x" * 50000}, {"name": "b.txt", "text": "User: " + "y" * 40000}]}).status_code == 200  # v1.4.3: 90k pooled now fine
    r = client.post("/api/score_transcripts", json={"files": [{"name": "long.txt", "text": "User: " + "x" * 300_100 + "\nAssistant: y"}]})
    assert r.status_code == 413 and "per-session limit" in r.json()["detail"]                     # one session > MAX_SESSION_CHARS
    r = client.post("/api/score_transcripts", json={"files": [{"name": f"q{i}__s.txt", "text": "User: " + "x" * 299_000 + "\nAssistant: y"} for i in range(7)]})
    assert r.status_code == 413 and "after parsing" in r.json()["detail"]                        # 7 x 299k = 2.09M pooled > MAX_CHARS
    lim = client.get("/api/score_transcripts/limits").json()
    assert lim["max_files"] == ra.MAX_FILES and lim["max_session_chars"] == ra.MAX_SESSION_CHARS and lim["max_raw_chars"] == ra.MAX_RAW_CHARS and lim["max_sessions"] == 24


def test_legacy_text_only_and_name_sanitising(client):
    r = client.post("/api/score_transcripts", json={"text": (FX / "sharegpt_2sessions.json").read_text(), "include_controls": False})
    assert r.status_code == 200 and r.json()["detected_format"] == "sharegpt" and r.json()["n_files"] == 0
    r = client.post("/api/score_transcripts", json={"files": [{"name": "../../etc/p1__x.txt", "text": "User: a\nAssistant: b"}], "include_controls": False})
    assert r.status_code == 200 and [x["participant_id"] for x in CALLS["recs"]] == ["p1"]


def test_v58_collisions_and_transcripts_combo(client):
    # N1a: forced pid over JSONL records that carry explicit session_idx -> renumbered, no collisions
    jl = "\n".join('{"participant_id":"z%d","session_idx":0,"task_id":"t","messages":[{"role":"user","content":"q%d"}]}' % (i, i) for i in range(3))
    r = client.post("/api/score_transcripts", json={"files": [{"name": "x.jsonl", "text": jl}], "participant_id": "boss", "include_controls": False})
    assert r.status_code == 200 and sorted((x["participant_id"], x["session_idx"]) for x in CALLS["recs"]) == [("boss", 0), ("boss", 1), ("boss", 2)]
    # N1b: .txt before .json with explicit idx 0 for the same stem
    r = client.post("/api/score_transcripts", json={"files": [{"name": "kim__a.txt", "text": "User: a\nAssistant: b"}, {"name": "kim.json", "text": '{"participant_id":"kim","session_idx":0,"messages":[{"role":"user","content":"c"}]}'}], "include_controls": False})
    got = sorted((x["participant_id"], x["session_idx"]) for x in CALLS["recs"]); assert r.status_code == 200 and len(set(got)) == 2, got
    # N3: transcripts + files rejected
    assert client.post("/api/score_transcripts", json={"transcripts": [{"participant_id": "a", "messages": [{"role": "user", "content": "x"}]}], "files": [{"name": "b.txt", "text": "User: y"}]}).status_code == 400
    # N2: n_unique_transcripts surfaced
    r = client.post("/api/score_transcripts", json={"files": [{"name": "a__1.txt", "text": "User: same\nAssistant: same"}, {"name": "a__2.txt", "text": "User: same\nAssistant: same"}], "include_controls": False})
    assert r.status_code == 200 and "n_unique_transcripts" in r.json()["summary"]

def _frames_export(n_tool_results=3, pad=0):
    """Minimal agent-session export: harness notice, typed turn with inline attachment JSON, tool loop, [System] preview message,
    thinking, a second typed turn separated from the first only by tool work, assistant prose split by a tool call, one child frame."""
    big = "R" * pad
    root_msgs = [
        {"role": "user", "_harness_notice": True, "content": [{"type": "text", "text": "[System] skill discovery ..."}]},
        {"role": "user", "_intent_id": "i1", "content": [{"type": "text", "text": 'is {"type":"attachment","id":"a","version_id":"v","filename":"brief.html","content_type":"text/html","size_bytes":9} the latest brief?'},
                                                        {"type": "text", "text": "[System] Attachment available: brief.html. Use read_file(...) to read it."}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "SECRET-THOUGHT"}, {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}]},
    ]
    for k in range(n_tool_results):
        root_msgs += [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{k}", "content": "TOOL-OUTPUT " + big}]},
                      {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{k+1}", "name": "bash", "input": {"cmd": "ls"}}]}]
    root_msgs += [
        {"role": "user", "_cell_images": ["x"], "content": [{"type": "text", "text": "[System] Attached file: fig.png (preview — not an artifact)"}, {"type": "image", "source": {"data": "AAAA" + big}}]},
        {"role": "user", "_intent_id": "i2", "content": "what do you mean 110 fold weaker?"},
        {"role": "assistant", "content": [{"type": "text", "text": "First half of the answer."}, {"type": "tool_use", "id": "t9", "name": "edit", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t9", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Second half of the answer."}]},
        {"role": "user", "_rolling_summary": "s", "content": [{"type": "text", "text": "[rolling-summary abc]"}]},
        {"role": "user", "_intent_id": "i3", "content": [{"type": "text", "text": "thanks, one more thing"}]},
    ]
    child = {"id": "c1", "parent_frame_id": "r1", "agent_name": "REVIEWER", "messages": [{"role": "user", "content": "SUBAGENT PROMPT " + big}, {"role": "assistant", "content": "SUBAGENT REPLY"}]}
    return {"export_version": "1.0", "root_frame_id": "r1", "conversation_name": "SD plan", "summary": {"user_email": None},
            "frames": [child, {"id": "r1", "parent_frame_id": None, "agent_name": "OPERON", "task_summary": "x", "messages": root_msgs}], "artifacts": []}


def test_frames_export_parsed(client):
    import json as _json
    ex = _frames_export()
    r = client.post("/api/score_transcripts", json={"files": [{"name": "07368628_2026-09-08T20-02-00.json", "text": _json.dumps(ex)}]})
    assert r.status_code == 200, r.text
    j = r.json(); assert j["detected_format"] == "frames" and j["n_sessions"] == 1
    rec = CALLS["recs"][0]
    assert rec["participant_id"] == "07368628_2026-09-08T20-02-00" and rec["task_id"] == "SD plan" and rec["submission"] is None
    roles = [m["role"] for m in rec["messages"]]; texts = [m["content"] for m in rec["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"], roles       # no trailing placeholder: no tool work after the last typed turn
    assert texts[0] == "is [attached: brief.html] the latest brief?"
    assert texts[1].startswith("[worked with tools (4 calls); no prose reply")          # 1 read_file + 3 bash before the second typed turn
    assert texts[2] == "what do you mean 110 fold weaker?"
    assert texts[3] == "First half of the answer.\n\nSecond half of the answer."        # prose split by a tool call is one turn
    assert texts[4] == "thanks, one more thing"
    blob = _json.dumps(rec)
    for bad in ("TOOL-OUTPUT", "SECRET-THOUGHT", "SUBAGENT", "[System]", "rolling-summary", "AAAA", "read_file("):
        assert bad not in blob, bad
    # email local part becomes the participant id when present; the participant_id box still overrides
    ex["summary"]["user_email"] = "kaylal@example.com"
    client.post("/api/score_transcripts", json={"files": [{"name": "x.json", "text": _json.dumps(ex)}]})
    assert CALLS["recs"][0]["participant_id"] == "kaylal"
    client.post("/api/score_transcripts", json={"files": [{"name": "x.json", "text": _json.dumps(ex)}, {"name": "y.json", "text": _json.dumps(ex)}], "participant_id": "me"})
    assert [(r["participant_id"], r["session_idx"]) for r in CALLS["recs"]] == [("me", 0), ("me", 1)]


def test_frames_export_multimegabyte_raw(client):
    """A 4 MB raw export (not trimmed by the browser) passes the raw gate and parses to a small session."""
    import json as _json
    ex = _frames_export(n_tool_results=40, pad=100_000)          # ~4.3 MB of tool output, image data and sub-agent text
    raw = _json.dumps(ex); assert len(raw) > 4_000_000
    r = client.post("/api/score_transcripts", json={"files": [{"name": "big.json", "text": raw}]})
    assert r.status_code == 200, r.text
    assert r.json()["n_chars"] < 500, r.json()["n_chars"]

def test_v59_chips_linear_and_exact(client):
    """V59 B1/S2: many attachment chips parse in linear time; a chip not followed by whitespace does not swallow typed text."""
    import json as _json, time as _time
    chip = lambda n: _json.dumps({"type": "attachment", "id": n, "version_id": "v", "filename": n + ".png", "artifact_ref": "{{artifact:v}}", "content_type": "image/png", "size_bytes": 1}, separators=(",", ":"))
    many = "   ".join(chip(f"c{i}") for i in range(60)) + " word"
    tricky = chip("a") + ": what about " + chip("b") + "? compare"
    ex = {"export_version": "1.0", "root_frame_id": "r", "frames": [{"id": "r", "parent_frame_id": None, "messages": [
        {"role": "user", "content": many}, {"role": "assistant", "content": "ok"},
        {"role": "user", "content": tricky}, {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        {"role": "user", "content": "   ".join(chip(f"d{i}") for i in range(40))},          # chips only: not a turn
    ]}]}
    t = _time.time()
    r = client.post("/api/score_transcripts", json={"files": [{"name": "x.json", "text": _json.dumps(ex)}]})
    assert r.status_code == 200, r.text
    assert _time.time() - t < 2.0
    msgs = CALLS["recs"][0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"].count("[attached: ") == 60 and msgs[0]["content"].endswith("word") and "artifact_ref" not in msgs[0]["content"]
    assert msgs[2]["content"] == "[attached: a.png]: what about [attached: b.png]? compare", msgs[2]["content"]


def test_v59_malformed_is_400_and_turn_rules(client):
    import json as _json
    for bad in ({"frames": [{"id": "r", "parent_frame_id": None, "messages": [{"role": 5, "content": "x"}]}], "summary": "s"},
                {"frames": []}, {"frames": [{"id": "r", "parent_frame_id": None}]},
                {"frames": [{"id": "r", "parent_frame_id": None, "messages": [{"role": "user", "content": [{"type": "tool_result", "content": "x"}]}]}]}):
        r = client.post("/api/score_transcripts", json={"files": [{"name": "b.json", "text": _json.dumps(bad)}]})
        assert r.status_code == 400, (bad, r.status_code, r.text)
    # two typed user messages with nothing from the assistant between them stay two turns (V59 N9); flags {} / "" count as set (S5)
    ex = {"frames": [{"id": "r", "parent_frame_id": None, "messages": [
        {"role": "user", "content": "build the graph"}, {"role": "user", "content": "try again"},
        {"role": "assistant", "content": [{"type": "text", "text": "built"}]},
        {"role": "user", "_harness_notice": {}, "content": "flagged with empty object: dropped"},
        {"role": "user", "_rolling_summary": "", "content": "flagged with empty string: dropped"},
        {"role": "user", "_harness_notice": False, "content": "flag false: kept"},
        {"role": "user", "_harness_notice": None, "content": "flag null: kept"}]}], "transcripts": [{"messages": []}]}   # N1: frames wins over 'transcripts'
    r = client.post("/api/score_transcripts", json={"files": [{"name": "n9.txt", "text": _json.dumps(ex)}]})       # N2: .txt-named export still parsed as an export
    assert r.status_code == 200, r.text
    assert [m["content"] for m in CALLS["recs"][0]["messages"]] == ["build the graph", "try again", "built", "flag false: kept", "flag null: kept"]

def test_v59b_quadratic_paths_and_bom(client):
    """V59b S6/N17: unmatched '[attached: ' runs, blank-line runs and unterminated chip starts parse in linear time; BOM-prefixed export parses."""
    import json as _json, time as _time
    cases = {"tags": "[attached: " * 27300 + " word", "blank": "\n\n \n" * 40000 + "[System] x\nword",
             "chipstarts": '{"type":"attachment", "a": ' * 8000 + " word"}
    for k, txt in cases.items():
        ex = {"frames": [{"id": "r", "parent_frame_id": None, "messages": [{"role": "user", "content": txt}, {"role": "assistant", "content": "ok"}]}]}
        t = _time.time()
        r = client.post("/api/score_transcripts", json={"files": [{"name": "q.json", "text": _json.dumps(ex)}]})
        assert r.status_code in (200, 413), (k, r.status_code, r.text[:200])
        assert _time.time() - t < 3.0, (k, _time.time() - t)
    ex = {"export_version": "1", "frames": [{"id": "r", "parent_frame_id": None, "messages": [{"role": "user", "content": "is " + _json.dumps({"type": "attachment", "id": "a", "filename": "b[1].png"}) + " new?"}, {"role": "assistant", "content": "yes"}]}]}
    r = client.post("/api/score_transcripts", json={"text": "\ufeff" + _json.dumps(ex)})
    assert r.status_code == 200, r.text
    assert CALLS["recs"][0]["messages"][0]["content"] == "is [attached: b_1_.png] new?"


def test_v59b_metrics_integer_ids(client):
    """V59b B2: judge output that numbers self-written targets as integers must score the same as string ids."""
    from est.transcripts import metrics
    j = {"targets_used": {"1": "a", "2": "b", "3": "c"}, "user_turns": [{"asks": [1, 2], "level": "specific"}, {"asks": [2], "level": "general", "retry": True}],
         "assistant_turns": [{"nonanswer": True}, {}], "provided": [1, 2], "used": [1]}
    js = {"targets_used": {"1": "a", "2": "b", "3": "c"}, "user_turns": [{"asks": ["1", "2"], "level": "specific"}, {"asks": ["2"], "level": "general", "retry": True}],
          "assistant_turns": [{"nonanswer": True}, {}], "provided": ["1", "2"], "used": ["1"]}
    a, b = metrics(j, None), metrics(js, None)
    for k in ("coverage", "specificity", "persistence", "verification", "uptake", "composite", "asked_ids", "provided_ids", "used_ids", "judge_invented_ids"):
        assert a[k] == b[k], (k, a[k], b[k])
    assert abs(a["coverage"] - 2 / 3) < 1e-9 and a["judge_invented_ids"] == []
    c = metrics(j, ["1", "2", "3", "4"])      # designer targets as strings, judge ints
    assert abs(c["coverage"] - 0.5) < 1e-9 and c["judge_invented_ids"] == []



def test_v15_judge_model_field(client):
    """v1.5: judge_model defaults to claude-sonnet-5, accepts 'opus'/'claude-opus-5', rejects anything else with 400."""
    base = {"text": "User: how do I fix my PCR?\nAssistant: check annealing temp\nUser: what temp exactly?\nAssistant: 58C"}
    r = client.post("/api/score_transcripts", json=base); assert r.status_code == 200, r.text
    assert CALLS["kw"].get("judge_model") == "claude-sonnet-5"
    r = client.post("/api/score_transcripts", json={**base, "judge_model": "opus"}); assert r.status_code == 200, r.text
    assert CALLS["kw"].get("judge_model") == "claude-opus-5"
    r = client.post("/api/score_transcripts", json={**base, "judge_model": "gpt-4o"}); assert r.status_code == 400 and "judge_model" in r.text


def test_v59c_shouldfix(client):
    """V59c SF2 deep tasks -> 4xx not 500; SF3 participant_id capped at 64 and applied via force_pid; SF5 BOM on txt paste and CSV."""
    txt = "User: first\nAssistant: a\nUser: second\nAssistant: b"
    r = client.post("/api/score_transcripts", json={"text": "\ufeff" + txt}); assert r.status_code == 200, r.text
    recs = CALLS["recs"]; assert [m["content"] for m in recs[0]["messages"] if m["role"] == "user"] == ["first", "second"]
    csv = "\ufeffparticipant_id,session_idx,role,content\np1,0,user,hello there\np1,0,assistant,hi\n"
    r = client.post("/api/score_transcripts", json={"files": [{"name": "x.csv", "text": csv}]}); assert r.status_code == 200, r.text
    assert CALLS["recs"][0]["participant_id"] == "p1"
    r = client.post("/api/score_transcripts", json={"text": txt, "participant_id": "p" * 65}); assert r.status_code == 400 and "participant_id" in r.text
    r = client.post("/api/score_transcripts", json={"text": txt, "participant_id": "  q17  "}); assert r.status_code == 200
    assert {x["participant_id"] for x in CALLS["recs"]} == {"q17"}
    deep = cur = {}
    for _ in range(3000): cur["a"] = {}; cur = cur["a"]
    try:
        body = json.dumps({"text": txt, "tasks": deep})
    except RecursionError:
        body = '{"text": %s, "tasks": %s}' % (json.dumps(txt), '{"a":' * 3000 + '{}' + '}' * 3000)
    r = client.post("/api/score_transcripts", content=body, headers={"content-type": "application/json"})
    assert r.status_code < 500, r.status_code


def test_v59c_chip_window(client):
    """V59c SF1: a well-formed attachment chip longer than 4096 bytes still collapses to [attached: name]."""
    import rank_transcripts as R
    chip = json.dumps({"type": "attachment", "filename": "big.csv", "meta": "x" * 6000})
    out = R._collapse_chips("please look at " + chip + " thanks") if hasattr(R, "_collapse_chips") else None
    if out is None:   # find the collapsing function by behaviour
        for name in dir(R):
            fn = getattr(R, name)
            if callable(fn) and name.startswith("_") and "chip" in name.lower():
                try: out = fn("please look at " + chip + " thanks"); break
                except TypeError: continue
    assert out is not None, "chip collapse function not found"
    assert "[attached: big.csv]" in out and "xxxxxx" not in out, out[:200]


def test_simplify_checklist_field(client):
    """v1.5 simplification: the checklist box reaches run() parsed; malformed JSON is a 400."""
    base = {"text": "User: how do I fix my PCR\nAssistant: details?\nUser: primers are 20-mers", "include_controls": False}
    r = client.post("/api/score_transcripts", json={**base, "checklist": "- primer design: exact sequences\n2. annealing temperature\n\nT3: template quality"})
    assert r.status_code == 200, r.text
    cl = CALLS["kw"]["checklist"]; assert list(cl) == ["*"] and list(cl["*"]) == ["T1", "T2", "T3"] and cl["*"]["T1"] == {"topic": "primer design", "detail": "exact sequences"}
    r = client.post("/api/score_transcripts", json={**base, "checklist": '{"taskA": ["x", {"topic": "y", "detail": "d"}], "taskB": []}'})
    assert r.status_code == 200 and list(CALLS["kw"]["checklist"]) == ["taskA"] and CALLS["kw"]["checklist"]["taskA"]["T2"]["detail"] == "d"
    r = client.post("/api/score_transcripts", json={**base, "checklist": '{"taskA": '}); assert r.status_code == 400
    r = client.post("/api/score_transcripts", json={**base, "checklist": "   "}); assert r.status_code == 200 and CALLS["kw"]["checklist"] is None


def test_simplify_pinned_checklist_and_overall(client):
    """run(): one checklist call per task without targets, reused for every session of that task; supplied checklist and
    designer targets take precedence; overall = mean of observed behaviours; ranking follows overall."""
    import tempfile, math
    import rank_transcripts as R
    writer_calls = []
    def fake_complete_json(system, messages, model=None, max_tokens=None):
        writer_calls.append(messages[0]["content"])
        return {"items": [{"topic": "primers", "detail": "sequences"}, {"topic": "annealing", "detail": "temperature in C"}, {"topic": "template", "detail": "ng and purity"}]}
    def fake_judge(rec, task, cache_dir, model=None):
        tg = list((task or {}).get("targets") or {})
        n_user = sum(m["role"] == "user" for m in rec["messages"])
        asks = tg[:n_user] if tg else [1, 2][:n_user]          # more turns, more items asked
        return {"user_turns": [{"i": i, "asks": [a], "level": "specific" if i == 0 else "general", "retry": False, "verify": i == 1} for i, a in enumerate(asks)],
                "assistant_turns": [{"j": j, "nonanswer": False} for j in range(n_user)], "provided": asks, "used": [],
                "targets_used": (task or {}).get("targets") or {"1": "a", "2": "b"}, "targets_given": bool(tg), "note": ""}
    R.complete_json, R.judge_session = fake_complete_json, fake_judge
    def rec(pid, si, task, n):
        msgs = []
        for t in range(n): msgs += [{"role": "user", "content": f"{pid} q{t} about {task}"}, {"role": "assistant", "content": "a"}]
        return {"participant_id": pid, "session_idx": si, "task_id": task, "messages": msgs, "submission": None}
    recs = [rec("ann", 0, "pcr", 3), rec("bob", 0, "pcr", 1), rec("ann", 1, "gel", 2)]
    with tempfile.TemporaryDirectory() as d:
        res = R.run(recs, None, d, workers=1)
        assert len(writer_calls) == 2                                     # one per task (pcr, gel), not per session
        res2 = R.run(recs, None, d, workers=1); assert len(writer_calls) == 2   # cached on disk
    cl = res["summary"]["checklists"]
    assert set(cl) == {"pcr", "gel"} and cl["pcr"]["source"] == "written by the tool" and cl["pcr"]["n_sessions"] == 2 and cl["pcr"]["items"] == {"T1": "primers", "T2": "annealing", "T3": "template"}
    S = {(x["participant_id"], x["session_idx"]): x for x in res["sessions"]}
    a0 = S[("ann", 0)]; b0 = S[("bob", 0)]
    assert a0["targets_given"] and a0["targets_source"] == "written by the tool" and a0["judge_invented_ids"] == []
    assert abs(a0["coverage"] - 1.0) < 1e-9 and abs(b0["coverage"] - 1 / 3) < 1e-9      # same 3-item checklist for both people on 'pcr'
    # overall = mean of observed: persistence NaN (no non-answer), uptake NaN (no submission) -> coverage, specificity, verification
    assert a0["persistence"] is None and a0["uptake"] is None and a0["n_observed"] == 3
    assert abs(a0["overall"] - (1.0 + 1 / 3 + 1.0) / 3) < 1e-9 and abs(a0["composite"] - (1.0 + 1 / 3 + 1.0) / 5) < 1e-9
    P = {x["participant_id"]: x for x in res["persons"]}
    assert P["ann"]["rank"] == 1 and P["bob"]["rank"] == 2 and P["ann"]["overall"] > P["bob"]["overall"]
    assert res["summary"]["tasks_yaml_supplied"] is False and sorted(res["summary"]["tasks_without_designer_targets"]) == ["gel", "pcr"]
    # supplied checklist beats the writer; designer targets beat both
    with tempfile.TemporaryDirectory() as d:
        writer_calls.clear()
        res = R.run(recs, {"gel": {"prompt": "run a gel", "targets": {"G1": {"topic": "percent agarose", "detail": ""}}}}, d, workers=1,
                    checklist={"*": {"T1": {"topic": "only item", "detail": ""}}})
        assert writer_calls == []
        cl = res["summary"]["checklists"]; assert cl["pcr"]["source"] == "supplied" and cl["gel"]["source"] == "designer" and cl["gel"]["items"] == {"G1": "percent agarose"}
        assert res["summary"]["tasks_without_designer_targets"] == ["pcr"]
        # derive off -> old behaviour, flagged per call
        res = R.run(recs, None, d, workers=1, derive_checklists=False)
        assert res["summary"]["checklists"]["pcr"]["source"] == "judge, per call" and writer_calls == []
        s0 = {(x["participant_id"], x["session_idx"]): x for x in res["sessions"]}[("ann", 0)]
        assert s0["targets_given"] is False and s0["targets_source"] == "judge, per call"


def test_v60_b1_nondefault_judge_model_scores(client):
    """V60 B1 regression: score_records must look results up with the same model-aware hash it judged under, so a
    non-default judge model yields judged rows (the live Opus 502 was every row unjudged) and lines carry topic: detail (S2)."""
    import tempfile
    import rank_transcripts as R
    seen_models = []
    def fake_judge(rec, task, cache_dir, model=None):
        seen_models.append(model)
        return {"user_turns": [{"i": 0, "asks": ["T1"], "level": "specific", "retry": False, "verify": False}],
                "assistant_turns": [{"j": 0, "nonanswer": False}], "provided": ["T1"], "used": [], "targets_used": {}, "targets_given": True, "note": ""}
    def fake_complete_json(system, messages, model=None, max_tokens=None):
        return {"items": [{"topic": "primers", "detail": "exact sequences"}, {"topic": "cycling", "detail": ""}]}
    R.judge_session, R.complete_json = fake_judge, fake_complete_json
    recs = [{"participant_id": "ann", "session_idx": 0, "task_id": "pcr", "submission": None,
             "messages": [{"role": "user", "content": "primer sequences?"}, {"role": "assistant", "content": "a"}]}]
    with tempfile.TemporaryDirectory() as d:
        for jm in ("claude-opus-5", "opus", "claude-sonnet-5"):
            res = R.run(recs, None, d, workers=1, judge_model=jm)
            assert res["summary"]["n_sessions_scored"] == 1, jm
            assert res["sessions"][0]["judged"] is True and res["summary"]["judge_model"] == R.JUDGE_MODELS[jm]
    assert seen_models[0] == "claude-opus-5" and seen_models[-1] == "claude-sonnet-5"
    assert res["summary"]["checklists"]["pcr"]["lines"] == ["primers: exact sequences", "cycling"]


if __name__ == "__main__":
    c = _client(); n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(c); n += 1; print("PASS", name)
    print(f"{n}/{n} passed")
