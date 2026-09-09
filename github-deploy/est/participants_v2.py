"""State-machine synthetic participants ("fixtures v2"). SPEC_AMENDMENTS.md A2, 2026-09-08.

Why: on the v1/v2 grids the free-form Haiku-scripted STRONG participant did not follow its own
script (fixated on one thread, never raised some categories, made the second T3 ask only half the
time). These fixtures are TEST FIXTURES for gate G1, not the system under test. Here a deterministic
Python policy decides every turn's ACTION; the LLM (Haiku) only (a) enumerates categories once from
the public task prompt and (b) phrases each pre-decided action as a short chat message, plus (STRONG
only) a cheap per-turn checker that reads the visible conversation.

ISOLATION GUARANTEE (do not weaken): a Fixture is built from ONLY (policy, public task_prompt,
nonce) and afterwards sees ONLY the visible conversation (list of {"role","content"}). It never
receives the item dict, hidden component texts, the topic map, `specific_requirement` strings or
the planted error, and this module deliberately imports nothing from est.items / est.controller /
est.scorer. The grid driver (run_synthetic_v3.py, build-time script, not shipped) passes item["task_prompt"] and Session.messages and nothing else.
Category lists are produced at run time by the LLM from the task prompt; the only fixed category is
the generic "reports from other people / lab chat / notes from other users" one required by the
SPEC's STRONG policy text ("has anyone else reported problems / any other notes or reports?").
"""
from __future__ import annotations
import hashlib, json, re
from . import llm as _llm
from .llm import HAIKU
from .participants import SUBMIT_SYS  # identical submission instructions to v1 (read-only import)

MAX_TURNS = {"WEAK": 2, "MEDIUM": 6, "STRONG": 10}

OTHER_CAT = {
    "name": "reports from other people in the lab: lab chat, notes or messages from other users, anyone else "
            "having the same problem or trouble with anything shared",
    "records": ["lab chat messages", "notes/messages left by other lab members", "other users' recent runs or complaints",
                "issue reports about shared equipment, shared reagents or shared solutions"],
    "is_other": True,
}

PHRASE_SYS = ("You are the PARTICIPANT (a lab member) chatting with an assistant that can look up this lab's records. "
              "Write your next chat message so that it carries out the INSTRUCTIONS exactly and completely, in natural "
              "first-person chat prose. {length} No role labels, no headings, no meta-commentary, do not mention "
              "instructions. Do not introduce topics that are not in the instructions. Session nonce: {nonce}.")

CHECK_SYS = ("You are a meticulous private note-checker working for the PARTICIPANT in a troubleshooting chat with a "
             "lab assistant. You only see the visible conversation. Be literal. Output JSON only.")


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def _convo(transcript: list[dict]) -> str:
    return "\n".join(f"{'YOU' if m['role']=='user' else 'ASSISTANT'}: {m['content']}" for m in transcript) or "(conversation not started)"


def _keywords(name: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", name) if w.lower() not in
            {"from", "with", "this", "that", "used", "their", "other", "about", "which", "were", "been", "have", "having",
             "anyone", "anything", "same", "problem", "trouble", "people", "shared", "actual", "actually"}]


def _digits(s: str) -> list[str]:
    return re.findall(r"\d+(?:[.,:]\d+)?", s)


# MEDIUM must ask in plain terms and never name records/measurements/settings (SPEC MEDIUM: "could it be the equipment?").
_GUARD = re.compile(r"\b(log|logs|logged|record|records|recorded|reading|readings|lot|lots|expiry|expired|expiration|setting|settings|"
                    r"entry|entries|history|concentration|concentrations|temperature|temperatures|amount|volume|dilution|diluted|"
                    r"date|dates|calibration|measurement|measured|nanodrop|number|numbers)\b", re.I)


class Fixture:
    """One synthetic participant for one session. Public API: max_turns, next_message(), observe(), submission(), record()."""

    def __init__(self, policy: str, task_prompt: str, nonce: str):
        assert policy in MAX_TURNS
        self.policy, self.task, self.nonce = policy, task_prompt, nonce
        self.max_turns = MAX_TURNS[policy]
        self.n_llm_calls = 0
        self.plan: list[dict] = []           # per-turn action log ("fixture_plan.turns")
        self.categories: list[dict] = []     # enumerated once on turn 1
        self.enum_raw = None
        # STRONG state
        self.new_queue: list[int] = []
        self.reask_queue: list[int] = []
        self.challenges: list[dict] = []
        self.pending_inc: dict | None = None
        self.seen_inc_keys: set[str] = set()
        self._last_asked: list[int] = []

    # ---------------- LLM helpers (counted) ----------------
    def _complete(self, sys, user, max_tokens=300):
        self.n_llm_calls += 1
        return _llm.complete(sys, [{"role": "user", "content": user}], HAIKU, max_tokens).strip()

    def _json(self, sys, user, max_tokens=700):
        self.n_llm_calls += 1
        return _llm.complete_json(sys, [{"role": "user", "content": user}], HAIKU, max_tokens)

    def _phrase(self, transcript, instructions: list[str], length: str, fallback: str, must: list[list[str]] | None = None) -> tuple[str, str]:
        """LLM phrases a pre-decided action. `must`: per instruction part, a list of tokens of which at least one must
        appear in the output; parts that are missing get their template sentence appended (adherence guard)."""
        sys = PHRASE_SYS.format(length=length, nonce=self.nonce)
        user = (f"TASK YOU WERE GIVEN:\n{self.task}\n\nCONVERSATION SO FAR:\n{_convo(transcript)}\n\n"
                "INSTRUCTIONS FOR YOUR NEXT MESSAGE (cover every numbered item):\n" +
                "\n".join(f"{i+1}. {p}" for i, p in enumerate(instructions)) + "\n\nWrite the message now.")
        src = "llm"
        try:
            msg = self._complete(sys, user, 400)
        except Exception as e:  # noqa
            msg, src = "", f"template(llm_error:{type(e).__name__})"
        msg = re.sub(r"^(YOU|PARTICIPANT|USER)\s*:\s*", "", msg.strip(), flags=re.I)
        if not msg or len(msg) > 1600:
            return fallback, ("template" if src == "llm" else src)
        if must:
            low = msg.lower()
            patches = []
            for part_tokens, templ in must:
                if part_tokens and not any(t.lower() in low for t in part_tokens):
                    patches.append(templ)
            if patches:
                msg = msg + " " + " ".join(patches)
                src = "llm+patch"
        return msg, src

    # ---------------- enumeration ----------------
    def _enumerate(self):
        if self.policy == "STRONG":
            user = (f"TASK:\n{self.task}\n\nYou are planning a careful investigation of THIS lab's own records. List exactly 7 "
                    "distinct categories of situation-specific causes worth checking, most likely first. Make them cover "
                    "different kinds of cause: the instrument/equipment used, each class of reagent or consumable involved, "
                    "the input material/sample itself, the protocol steps and settings as actually performed or programmed, "
                    "storage/environment, and shared resources. For each give a short noun-phrase name (<=8 words) and 2-4 "
                    "examples of the concrete records a lab would hold about it (log entries, measured readings, saved "
                    f"settings, lot/expiry entries, dates, maintenance records). Session nonce: {self.nonce}.\n"
                    'Return JSON: {"categories": [{"name": "...", "records": ["...", "..."]}, ...]}')
            cats = []
            try:
                j = self._json("You help a careful troubleshooter plan. Output JSON only.", user, 900)
                self.enum_raw = j
                for c in j.get("categories", []):
                    if isinstance(c, dict) and str(c.get("name", "")).strip():
                        recs = [str(r) for r in (c.get("records") or []) if str(r).strip()][:4]
                        cats.append({"name": str(c["name"]).strip()[:120], "records": recs or ["log entries", "readings", "dates"]})
                    elif isinstance(c, str) and c.strip():
                        cats.append({"name": c.strip()[:120], "records": ["log entries", "readings", "saved settings", "dates"]})
            except Exception as e:  # noqa
                self.enum_raw = {"error": repr(e)[:300]}
            if len(cats) < 4:   # deterministic generic fallback (task-agnostic)
                cats = [{"name": n, "records": r} for n, r in [
                    ("the instrument/equipment used", ["equipment log", "calibration/maintenance records", "error logs"]),
                    ("the main reagents/kits used", ["inventory lot and expiry entries", "date opened", "storage log"]),
                    ("the input sample/material", ["prep record", "QC measurement", "storage/freeze-thaw history"]),
                    ("the protocol/settings as actually run", ["saved program/settings", "notebook entry", "edit history"]),
                    ("consumables and solutions", ["preparation dates", "lot numbers", "who made them"]),
                    ("storage and environment", ["temperature logs", "alarm history", "dates"]),
                    ("timeline of the failed attempts", ["dates of each attempt", "what changed between them"])]]
            cats = cats[:8]
            other = dict(OTHER_CAT)
            cats.insert(1, other)          # asked on turn 1, so a re-ask is always possible well before the sweep
            self.categories = [{"name": c["name"], "records": c["records"], "is_other": bool(c.get("is_other")),
                                "asks": [], "answered": False, "answered_turn": None} for c in cats]
            self.new_queue = list(range(len(self.categories)))
        elif self.policy == "MEDIUM":
            user = (f"TASK:\n{self.task}\n\nList exactly 6 distinct, likely categories of cause for this problem, most likely "
                    "first. Each category must name the THING that might be at fault as a short everyday noun phrase of 1-4 "
                    "words (like 'the equipment', 'the ingredients', 'the starting material') and NOT a measurement, property, "
                    "amount, setting or failure mechanism of it, and with no mention of records or logs. "
                    f"Session nonce: {self.nonce}.\n" 'Return JSON: {"categories": ["...", "..."]}')
            cats = []
            try:
                j = self._json("You help someone think through a problem. Output JSON only.", user, 400)
                self.enum_raw = j
                cats = [str(c.get("name") if isinstance(c, dict) else c).strip()[:80] for c in j.get("categories", [])]
                cats = [self._plain(c) for c in cats if c and c.lower() != "none"]
                cats = [c for c in cats if c]
            except Exception as e:  # noqa
                self.enum_raw = {"error": repr(e)[:300]}
            if len(cats) < 3:
                cats = ["the equipment", "the reagents", "the starting material", "the protocol", "storage conditions", "contamination"]
            self.categories = [{"name": c, "asks": [], "is_other": False} for c in cats[:6]]

    @staticmethod
    def _plain(name: str) -> str:
        """Strip record/measurement words from a MEDIUM category name so the plain-language question names only the thing."""
        words = [w for w in re.split(r"\s+", name.strip()) if w and not _GUARD.search(w)]
        out = " ".join(words).strip(" ,;:/-")
        out = re.sub(r"\b(and|or|of|&)\s*$", "", out).strip(" ,;:/-")
        return out[:60]

    # ---------------- STRONG policy ----------------
    def _strong_turn(self, transcript, t):
        acts, instr, must, templ = [], [], [], []
        final = t == self.max_turns
        if final:
            open_idx = [i for i, c in enumerate(self.categories) if not c["answered"]]
            names = [self.categories[i]["name"] for i in open_idx] or [c["name"] for c in self.categories]
            acts.append({"type": "SWEEP", "open_categories": names, "all_answered": not open_idx})
            listing = "; ".join(f"({k+1}) {n}" for k, n in enumerate(names))
            instr.append("This is your last message. Say that before you write this up you want anything in the records not yet "
                         "covered, then explicitly go through these still-open items one by one, asking for the concrete record "
                         f"(log entry, reading, lot/expiry, setting, message) on each: {listing}. End by asking whether there is "
                         "anything else in the logs, inventory or lab chat that you have not been told.")
            templ.append(f"Before I write this up, please list anything in the records we have not covered. Specifically, I still need the "
                         f"actual record for each of these: {listing}. And is there anything else in the logs, inventory or lab chat I haven't been told?")
            for i in open_idx:
                self.categories[i]["asks"].append(t)
            must = [( _keywords(n)[:3], f"Also, specifically: what do the records show for {n}?") for n in names]
            self._last_asked = open_idx
            length = "3-6 sentences."
        else:
            slots = 2
            if self.pending_inc is not None and len(self.challenges) < 2:
                inc = self.pending_inc; self.pending_inc = None
                self.challenges.append({"turn": t, **inc})
                acts.append({"type": "CHALLENGE", "figure_a": inc["figure_a"], "figure_b": inc["figure_b"], "why": inc["why"], "flagged_after_turn": inc["flagged_after_turn"]})
                instr.append(f"Start by challenging an inconsistency in what the assistant told you: quote these two figures exactly, "
                             f"\"{inc['figure_a']}\" and \"{inc['figure_b']}\", say they do not reconcile ({inc['why']}), and ask it to "
                             "re-check that record and confirm which figure is correct.")
                templ.append(f"One thing doesn't add up: you said \"{inc['figure_a']}\" but also \"{inc['figure_b']}\" — {inc['why']}. "
                             "Can you re-check that record and tell me which is correct?")
                must.append((_digits(inc["figure_a"]) + _digits(inc["figure_b"]), templ[-1]))
                slots = 1
            due = [i for i in self.reask_queue if self.categories[i]["asks"] and self.categories[i]["asks"][-1] <= t - 2]
            due.sort(key=lambda i: (not self.categories[i]["is_other"], self.categories[i]["asks"][-1]))  # other-reports re-ask first
            picks: list[tuple[str, int]] = []
            if due:
                i = due.pop(0); self.reask_queue.remove(i); picks.append(("REASK", i))
            while len(picks) < slots and self.new_queue:
                picks.append(("ASK", self.new_queue.pop(0)))
            while len(picks) < slots and due:
                i = due.pop(0); self.reask_queue.remove(i); picks.append(("REASK", i))
            if len(picks) < slots:
                # spare capacity: third, most pointed ask of anything still unanswered (other-reports first), max 3 asks/category
                spare = [i for i, c in enumerate(self.categories) if not c["answered"] and 0 < len(c["asks"]) < 3
                         and c["asks"][-1] <= t - 1 and i not in self.reask_queue and i not in [p[1] for p in picks]]
                spare.sort(key=lambda i: (not self.categories[i]["is_other"], self.categories[i]["asks"][-1]))
                while len(picks) < slots and spare:
                    picks.append(("REASK", spare.pop(0)))
            if not picks and not acts:
                names = [c["name"] for c in self.categories]
                acts.append({"type": "OPEN", "note": "all categories answered; open request for any other records"})
                instr.append("Everything you asked about has been answered. Ask whether there is anything else at all in the logs, "
                             "inventory, equipment records or lab chat relevant to this problem that you have not been told yet, "
                             "and ask for the concrete entry if so.")
                templ.append("Is there anything else at all in the logs, inventory, equipment records or lab chat relevant to this that I haven't been told? If so, give me the actual entry.")
            for kind, i in picks:
                c = self.categories[i]
                c["asks"].append(t)
                n_ask = len(c["asks"])
                acts.append({"type": kind, "category": c["name"], "category_idx": i, "ask_no": n_ask})
                recs = ", ".join(c["records"])
                if kind == "ASK" and c["is_other"]:
                    instr.append("Ask whether anyone else in the lab has reported the same problem or anything unusual recently: ask the "
                                 "assistant to check the lab chat, notes or messages from other users, and any reports or complaints about "
                                 "shared equipment, shared reagents or shared solutions, and to give you the actual messages/entries.")
                    templ.append("Has anyone else in the lab reported the same problem or anything odd recently? Please check the lab chat, any notes or "
                                 "messages from other users, and any reports about shared equipment or shared reagents/solutions, and give me the actual entries.")
                elif kind == "ASK":
                    instr.append(f"Ask the assistant to pull THIS lab's concrete records about: {c['name']}. Name the specific records you want "
                                 f"looked up (for example: {recs}) and ask for the actual entries — the values, dates, lot numbers or settings "
                                 "as recorded — not general advice.")
                    templ.append(f"Can you pull the lab's actual records on {c['name']} — e.g. {recs}? I want the specific entries (values, dates, lots, settings as recorded), not general advice.")
                elif c["is_other"]:
                    instr.append(f"You already asked (ask #{n_ask - 1}) whether anyone else has reported problems and got nothing concrete. Ask AGAIN, "
                                 "pointedly and on purpose: request that the assistant search the lab chat and other users' notes/messages again "
                                 "for anyone else with failures, complaints or warnings (including about shared equipment, water, buffers, "
                                 "solutions or other shared reagents), and report exactly what is there, even if minor.")
                    templ.append("I asked before but want you to check again, specifically: search the lab chat and other users' notes once more — has anyone "
                                 "else had failures, or posted any complaint or warning (including about shared equipment, water, buffers or other shared reagents)? Tell me exactly what's there, even if minor.")
                else:
                    instr.append(f"You asked before about {c['name']} and did not get a concrete record. Re-ask MORE pointedly (this is deliberate "
                                 f"ask #{n_ask}): say you want the actual record looked up again, name the exact entries you expect to exist "
                                 f"({recs}), and ask for the specific numbers, dates, lot/expiry or log lines.")
                    templ.append(f"Coming back to {c['name']}: I still don't have an actual record. Please look again and give me the specific entries — {recs} — with the exact numbers/dates.")
                must.append((_keywords(c["name"])[:3] or _keywords(recs)[:2], templ[-1]))
            self._last_asked = [i for _, i in picks]
            length = "2-4 sentences." if len(instr) > 1 else "1-3 sentences."
        fallback = " ".join(templ)
        msg, src = self._phrase(transcript, instr, length, fallback, must)
        self.plan.append({"turn": t, "actions": acts, "instructions": instr, "message_source": src})
        return msg

    def _strong_observe(self, transcript, t):
        asked = [self.categories[i]["name"] for i in self._last_asked]
        check_numbers = len(self.challenges) < 2
        user = (f"CONVERSATION SO FAR:\n{_convo(transcript)}\n\n"
                "A) For each CATEGORY the participant asked about in their LATEST message, decide whether the assistant's LATEST "
                "reply answered it with AT LEAST ONE concrete lab-specific record about that category (a specific log entry, "
                "measured value, date, lot number, saved setting, or a named person's message/note) = true, even if not every "
                "record the participant listed was found. Only generic advice, 'I don't see a record on that', or an offer to "
                f"check later = false.\nCATEGORIES ASKED: {json.dumps(asked)}\n\n" +
                ("B) Independently audit ALL figures the ASSISTANT has stated anywhere in the conversation: redo every dilution, "
                 "ratio, percentage, concentration, volume, mass, count, duration, time and date calculation, and compare figures "
                 "that describe the same thing. List each pair of the assistant's own stated figures that do NOT reconcile with "
                 "each other, quoting both exactly as written. Only internal contradictions/arithmetic that does not work out — "
                 "not values that are merely surprising or suboptimal. Empty list if everything reconciles.\n" if check_numbers else
                 "B) (skip) return an empty inconsistencies list.\n") +
                'Return JSON: {"answered": {"<category name>": true|false}, "inconsistencies": [{"figure_a": "...", "figure_b": "...", "why": "<=25 words"}]}')
        entry = {"turn": t, "asked": asked}
        try:
            j = self._json(CHECK_SYS, user, 700)
            ans = j.get("answered", {}) if isinstance(j.get("answered"), dict) else {}
            incs = [x for x in (j.get("inconsistencies") or []) if isinstance(x, dict) and x.get("figure_a") and x.get("figure_b")][:4]
            entry.update({"answered": ans, "inconsistencies": incs})
        except Exception as e:  # noqa
            ans, incs = {}, []
            entry.update({"error": repr(e)[:200], "answered": {}, "inconsistencies": []})
        # map answers back onto categories (by exact name, else by order)
        for k, i in enumerate(self._last_asked):
            c = self.categories[i]
            v = ans.get(c["name"])
            if v is None and k < len(ans):
                v = list(ans.values())[k]
            if bool(v) and v not in ("false", "False", 0):
                c["answered"], c["answered_turn"] = True, t
                if i in self.reask_queue:
                    self.reask_queue.remove(i)
            else:
                lim = 3 if c["is_other"] else 2
                if len(c["asks"]) < lim and i not in self.reask_queue and t < self.max_turns:
                    self.reask_queue.append(i)
        # queue a challenge for the first new inconsistency
        if check_numbers and self.pending_inc is None:
            for x in incs:
                toks = sorted(set(_digits(str(x["figure_a"])) + _digits(str(x["figure_b"]))))
                key = "|".join(toks) or (str(x["figure_a"]) + "|" + str(x["figure_b"]))[:80]
                already = any(set(toks) & set(ch.get("tokens", [])) for ch in self.challenges) if toks else False
                if key in self.seen_inc_keys or already:
                    continue
                self.seen_inc_keys.add(key)
                self.pending_inc = {"figure_a": str(x["figure_a"])[:160], "figure_b": str(x["figure_b"])[:160],
                                    "why": str(x.get("why", "these do not reconcile"))[:200], "flagged_after_turn": t, "tokens": toks}
                break
        entry["reask_queue_after"] = [self.categories[i]["name"] for i in self.reask_queue]
        entry["pending_challenge"] = None if self.pending_inc is None else {k: self.pending_inc[k] for k in ("figure_a", "figure_b")}
        self.plan[-1]["checker"] = entry

    # ---------------- MEDIUM policy ----------------
    def _medium_turn(self, transcript, t):
        if t - 1 < len(self.categories):
            c = self.categories[t - 1]; c["asks"].append(t)
            acts = [{"type": "GENERAL", "category": c["name"], "category_idx": t - 1}]
            instr = [f"Ask ONE general, plain-language question about whether the problem could be something to do with: {c['name']}. "
                     "Keep it conversational and short, like 'could it be something with the ...?'. Name only the thing itself: do NOT "
                     "mention amounts, concentrations, temperatures, times, settings, dates, lot numbers, expiry, records, logs, "
                     "readings or any specific mechanism; do NOT ask the assistant to look anything up; do NOT refer back to or "
                     "question anything it said earlier."]
            fallback = f"Could it be something to do with {c['name']}?"
            msg, src = self._phrase(transcript, instr, "1-2 sentences.", fallback, [(_keywords(c["name"])[:3], fallback)])
            if _GUARD.search(msg):
                msg, src = fallback, "template(guard:record_words)"
        else:
            acts = [{"type": "GENERIC_FOLLOWUP"}]
            instr = ["generic follow-up"]
            msg, src = "Thanks — is there anything else you think we should consider?", "template"
        self.plan.append({"turn": t, "actions": acts, "instructions": instr, "message_source": src})
        return msg

    # ---------------- WEAK policy ----------------
    def _weak_turn(self, transcript, t):
        if t == 1:
            instr = ["Write ONE broad opening question that basically restates the task in your own words and asks why this might be "
                     "happening or what to watch out for. Do NOT name any particular cause, step, reagent, instrument, record or log."]
            fallback = "We've had this fail three times in a row now — any idea why this might be happening, or what we should watch out for?"
            msg, src = self._phrase(transcript, instr, "1-2 sentences.", fallback)
            acts = [{"type": "BROAD_RESTATEMENT"}]
        else:
            variants = ["Ok thanks. Anything else? What should we do?",
                        "Thanks, that helps. Is there anything else, and what would you suggest we do next?",
                        "Got it. Anything else I should know? What do we do now?"]
            msg, src, instr = variants[_h(self.nonce) % len(variants)], "template", ["generic follow-up"]
            acts = [{"type": "GENERIC_FOLLOWUP"}]
        self.plan.append({"turn": t, "actions": acts, "instructions": instr, "message_source": src})
        return msg

    # ---------------- public API ----------------
    def next_message(self, transcript: list[dict], turn_idx: int) -> str:
        assert 1 <= turn_idx <= self.max_turns
        if turn_idx == 1 and self.policy in ("STRONG", "MEDIUM") and not self.categories:
            self._enumerate()
        if self.policy == "STRONG":
            return self._strong_turn(transcript, turn_idx)
        if self.policy == "MEDIUM":
            return self._medium_turn(transcript, turn_idx)
        return self._weak_turn(transcript, turn_idx)

    def observe(self, transcript: list[dict], turn_idx: int) -> None:
        """Called after the assistant reply is appended. Only STRONG uses it (checker call)."""
        if self.policy == "STRONG":
            self._strong_observe(transcript, turn_idx)

    def submission(self, transcript: list[dict]) -> str:
        sys = SUBMIT_SYS[self.policy] + f" Session nonce: {self.nonce}. Output only the submission text."
        return self._complete(sys, f"TASK:\n{self.task}\n\nCONVERSATION:\n{_convo(transcript)}\n\nWrite the submission now.", 700 if self.policy != "STRONG" else 900)

    def record(self) -> dict:
        cats = []
        for c in self.categories:
            d = {"name": c["name"], "asks": c["asks"]}
            if self.policy == "STRONG":
                d.update({"records": c["records"], "is_other": c["is_other"], "answered": c["answered"], "answered_turn": c["answered_turn"]})
            cats.append(d)
        return {"fixture_version": "v2-state-machine (A2 2026-09-08)", "policy": self.policy, "max_turns": self.max_turns,
                "nonce": self.nonce, "enumeration_raw": self.enum_raw, "categories": cats, "turns": self.plan,
                "challenges": [{k: v for k, v in ch.items() if k != "tokens"} for ch in self.challenges],
                "reask_queue_final": [self.categories[i]["name"] for i in self.reask_queue], "n_llm_calls_fixture": self.n_llm_calls}
