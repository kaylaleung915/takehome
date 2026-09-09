"""Export EST session records (runs/*.json, runs/human/*.json) to the trial transcripts.jsonl schema
(trial/SCHEMA.md) so pre-trial levels and in-trial sessions are scored by the same transcript judge."""
from __future__ import annotations
import json, sys, glob, os


def record_to_transcript(rec: dict, participant_id: str, session_idx: int) -> dict:
    return {"participant_id": participant_id, "session_idx": session_idx, "task_id": f"est:{rec['item_id']}",
            "messages": rec["messages"], "submission": rec.get("submission"),
            "source": "est", "est_score": (rec.get("score") or {}).get("subscales")}


def tasks_from_items() -> dict:
    """Designer decomposition for EST levels: targets = gated records C3..C7 (topic + text)."""
    from est.items import load_item, list_items
    out = {}
    for iid in list_items():
        it = load_item(iid)
        out[f"est:{iid}"] = {"prompt": it["task_prompt"].strip(),
                             "targets": {c: {"topic": v.get("topic", ""), "detail": v["text"]}
                                         for c, v in it["components"].items() if c in it["gated_ids"]}}
    return out


if __name__ == "__main__":
    # usage: python -m est.export runs/human out.jsonl   (participant_id taken from filename stem)
    src, dst = sys.argv[1], sys.argv[2]
    with open(dst, "w") as f:
        for i, p in enumerate(sorted(glob.glob(os.path.join(src, "*.json")))):
            rec = json.load(open(p))
            f.write(json.dumps(record_to_transcript(rec, os.path.basename(p)[:-5], i)) + "\n")
    print("wrote", dst)
