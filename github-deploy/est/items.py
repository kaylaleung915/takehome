import yaml, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
def load_item(item_id: str) -> dict:
    d = yaml.safe_load(open(ROOT / "items" / f"{item_id}.yaml"))
    d["gated_ids"] = [c for c in d["components"] if d["components"][c]["tier"] in ("T1", "T2", "T3")]
    return d
def list_items():
    return sorted(p.stem for p in (ROOT / "items").glob("*.yaml"))
def public_view(item: dict) -> dict:
    return {"id": item["id"], "title": item["title"], "domain": item["domain"], "task_prompt": item["task_prompt"]}
