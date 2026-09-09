"""Trait-driven simulated participant (demo_trial_v2). WHAT the participant does each turn is decided in Python from
five continuous latent traits and a per-session RNG; the LLM (HAIKU by default) only PHRASES the chosen action and sees
only the public task prompt and the visible conversation, never the hidden components, tiers or planted error.

Traits (all in (0,1)):
  decompose    number of chat turns = 2 + Binomial(8, decompose); also P(catch-all sweep on the last turn)
  ask_specific per topic, P(asking for the concrete record/number/log) vs asking about the topic generally
  persist      P(re-asking, more pointedly, when a cheap classifier says the previous reply gave nothing specific)
  verify       P(running one figure check on the visible conversation at some turn of the session; per-turn hazard calibrated so the
               session-level probability equals the trait; if the check finds non-reconciling numbers, challenge)
  synthesise   P(itemised-with-figures submission) vs a brief general summary
Different sessions of the same participant use different RNG streams, so two sessions are independent realisations of
the same latent person. Nothing here is human data."""
from __future__ import annotations
import json
import numpy as np
from .llm import complete, complete_json, HAIKU, SONNET

TRAITS = ["decompose", "ask_specific", "persist", "verify", "synthesise"]
OFFSETS = {"decompose": 0.0, "ask_specific": 0.0, "persist": -0.3, "verify": -0.4, "synthesise": 0.3}
G_LOAD, E_LOAD = 0.9, 0.6


def draw_traits(rng: np.random.Generator) -> dict:
    """g ~ N(0,1); trait_k = logistic(0.9 g + 0.6 e_k + offset_k), e_k ~ N(0,1)."""
    g = float(rng.normal())
    e = {k: float(rng.normal()) for k in TRAITS}
    tr = {k: float(1 / (1 + np.exp(-(G_LOAD * g + E_LOAD * e[k] + OFFSETS[k])))) for k in TRAITS}
    return {"g": g, "e": e, "traits": tr}


PHRASE_SYS = """You are role-playing a participant (a junior lab member) chatting with an AI records assistant about a
lab problem. Write ONLY the participant's next chat message: 1-3 sentences, natural and conversational, no role labels,
no meta-commentary, no lists of many questions. Follow the INSTRUCTION exactly and ask about nothing beyond it. You know
only what is in the TASK and the CONVERSATION; never invent lab records."""

TOPICS_SYS = """You are helping simulate a study participant. From the TASK description alone (you have no other
information), list distinct categories of situation-specific things (records, logs, equipment, materials, people,
procedures) that could be worth asking the lab's records assistant about, most likely/important first. Each topic is a
short noun phrase (<=8 words). Do not repeat the background already stated in the task."""

NONANSWER_SYS = """You are a strict yes/no classifier. Given a participant QUESTION and the assistant REPLY, decide whether
the reply provided at least one situation-specific record that answers the question (a concrete logged fact: a reading,
number, date, named entry, note or report about the thing asked). Generic advice, 'I don't see a record of that', or
records about a different topic than the one asked = false."""

CHECK_SYS = """You are a careful numerate reader. Examine every number, volume, concentration, dilution, percentage,
date, time, count and label stated in the ASSISTANT messages of the conversation. Do the arithmetic. List every case
where two stated figures do not reconcile with each other (e.g. stated volumes that do not give the stated percentage
or dilution, dates/times out of order, counts that do not add up). Be concrete: quote the figures. If everything
reconciles, return an empty list. Do not list merely surprising values, only internal inconsistencies."""

SUBMIT_ITEMISED = ("Write the participant's final written answer to the task: an itemised list of EVERY situation-specific fact learned in "
                   "the conversation, with the exact numbers/dates as stated, each with a recommended action, plus a short section "
                   "'Inconsistencies noticed' ONLY if you (the participant, 'YOU' in the conversation) explicitly questioned figures during the chat; "
                   "do not check any arithmetic yourself now and omit the section otherwise. Use only facts from the conversation.")
SUBMIT_BRIEF = ("Write the participant's final written answer to the task: 3-5 sentences summarising, in general terms, what the likely "
                "problems are and what to do. Do not itemise; do not add facts that were not in the conversation.")
NOASSIST_SYS = """You are role-playing a junior lab member who must answer the TASK with NO assistant and NO access to any of the lab's
records, logs or chat: answer from general textbook knowledge only. Never invent lab-specific records, numbers, dates or names."""


class Persona:
    def __init__(self, traits: dict, rng: np.random.Generator, model: str = HAIKU, tag: str = ""):
        self.tr = traits; self.rng = rng; self.model = model; self.tag = tag
        self.n_turns = int(2 + rng.binomial(8, traits["decompose"]))
        self.topics: list[str] = []
        self.ti = 0                       # next unopened topic
        self.pending_reask: str | None = None
        self.reasks: dict[str, int] = {}
        self.challenged = False
        self.checked = False              # at most one figure check per session
        self.decisions: list[dict] = []   # per-turn ground truth of what Python decided
        self.last_topic: str | None = None
        self.last_kind: str | None = None

    # ---- LLM helpers (public information only) -------------------------------------------------
    def _convo(self, transcript):
        return "\n".join(f"{'YOU' if m['role']=='user' else 'ASSISTANT'}: {m['content']}" for m in transcript) or "(conversation not started)"

    def plan_topics(self, task_prompt: str):
        k = 10
        try:
            j = complete_json(TOPICS_SYS, [{"role": "user", "content": f"TASK:\n{task_prompt}\n\nReturn JSON {{\"topics\": [{k} strings]}}"}], self.model, 400)
            tp = [str(t) for t in j.get("topics", []) if str(t).strip()][:k]
        except Exception:
            tp = []
        if not tp:
            tp = ["equipment used", "reagents and materials", "the procedure as performed", "the starting material", "other people's recent results", "environmental conditions", "recent changes in the lab"]
        # person-specific ordering noise: mostly likelihood order, occasionally swapped
        order = np.argsort(np.arange(len(tp)) + self.rng.normal(0, 1.0, len(tp)))
        self.topics = [tp[i] for i in order]

    def _phrase(self, task_prompt, transcript, instruction):
        user = f"TASK:\n{task_prompt}\n\nCONVERSATION SO FAR:\n{self._convo(transcript)}\n\nINSTRUCTION for your next message: {instruction}\n\n(session {self.tag}) Write the message now."
        return complete(PHRASE_SYS, [{"role": "user", "content": user}], self.model, 300).strip()

    def reply_was_specific(self, question: str, reply: str) -> bool:
        try:
            j = complete_json(NONANSWER_SYS, [{"role": "user", "content": f"QUESTION:\n{question}\n\nREPLY:\n{reply}\n\nReturn JSON {{\"specific\": true|false}}"}], self.model, 60)
            return bool(j.get("specific", False))
        except Exception:
            return True

    def check_figures(self, transcript) -> list[str]:
        try:
            j = complete_json(CHECK_SYS, [{"role": "user", "content": f"CONVERSATION:\n{self._convo(transcript)}\n\nReturn JSON {{\"issues\": [\"...\"]}}"}], self.model, 500)
            return [str(x) for x in j.get("issues", []) if str(x).strip()]
        except Exception:
            return []

    # ---- policy ------------------------------------------------------------------------------------
    def observe(self, transcript):
        """After an assistant reply: decide (trait persist) whether to re-ask the last topic."""
        if self.last_topic is None or len(transcript) < 2:
            return
        q, r = transcript[-2]["content"], transcript[-1]["content"]
        specific = self.reply_was_specific(q, r)
        d = {"after_turn": len(transcript) // 2, "topic": self.last_topic, "reply_specific": specific, "reask": False}
        if not specific and self.reasks.get(self.last_topic, 0) < 1:   # at most one re-ask per topic
            if self.rng.random() < self.tr["persist"]:
                self.pending_reask = self.last_topic; self.reasks[self.last_topic] = self.reasks.get(self.last_topic, 0) + 1; d["reask"] = True
        self.decisions.append({"observe": d})

    def next_message(self, task_prompt: str, transcript: list, turn_idx: int) -> str:
        if not self.topics:
            self.plan_topics(task_prompt)
        kind, topic, extra = None, None, None
        # verify: check the figures given so far at a per-turn hazard h chosen so that P(at least one check in the session)
        # equals the verify trait: h = 1-(1-verify)^(1/(n_turns-1)) over the n_turns-1 turns that have something to check
        # (v0 used hazard = verify per turn, which compounded to ~0.94 per session; preserved in sessions_v0_verify_saturated/)
        h = 1 - (1 - self.tr["verify"]) ** (1 / max(1, self.n_turns - 1))
        if transcript and not self.checked and self.rng.random() < h:
            self.checked = True
            issues = self.check_figures(transcript)
            self.decisions.append({"turn": turn_idx, "checked_figures": True, "issues_found": issues})
            if issues:
                kind, extra = "challenge", issues[:2]; self.challenged = True
        if kind is None and self.pending_reask:
            kind, topic = "reask", self.pending_reask; self.pending_reask = None
        if kind is None and turn_idx == self.n_turns and turn_idx > 1 and self.rng.random() < self.tr["decompose"]:
            kind = "sweep"
        if kind is None:
            if self.ti < len(self.topics):
                topic = self.topics[self.ti]; self.ti += 1
            else:
                topic = None
            if topic is None:
                kind = "sweep"
            else:
                kind = "specific" if self.rng.random() < self.tr["ask_specific"] else "general"
        instr = {
            "specific": f"Ask about this ONE topic: '{topic}'. Ask for the CONCRETE record: the actual log entry, reading, measurement, number, date, saved setting or note the lab has on it.",
            "general": f"Ask about this ONE topic in general terms: '{topic}' (e.g. 'could it be something with ...?', 'was everything OK with ...?'). Do NOT request specific records, logs, readings, numbers or dates.",
            "reask": f"The assistant did not give a specific record on '{topic}' when you asked. Push back and re-ask more pointedly: name the exact record, log entry, measurement or report you want it to look up on that topic.",
            "challenge": f"Point out that these figures the assistant gave do not add up, quoting them, and ask it to double-check the record: {json.dumps(extra)}",
            "sweep": "Ask a catch-all: whether there are any other notes, reports from other lab members, chat messages or records of anyone else having problems that haven't come up yet.",
        }[kind]
        self.last_topic = topic if kind in ("specific", "general", "reask") else ("__sweep__" if kind == "sweep" else None)
        self.last_kind = kind
        self.decisions.append({"turn": turn_idx, "kind": kind, "topic": topic})
        return self._phrase(task_prompt, transcript, instr)

    def submission(self, task_prompt: str, transcript: list) -> str:
        itemised = self.rng.random() < self.tr["synthesise"]
        self.decisions.append({"submission": "itemised" if itemised else "brief"})
        sys = (SUBMIT_ITEMISED if itemised else SUBMIT_BRIEF) + f" (session {self.tag}) Output only the answer text."
        return complete(sys, [{"role": "user", "content": f"TASK:\n{task_prompt}\n\nCONVERSATION:\n{self._convo(transcript)}\n\nWrite the answer now."}], self.model, 800).strip()

    def no_assistant_answer(self, task_prompt: str) -> str:
        """Control condition: answer the task with no assistant and no records (general knowledge only)."""
        itemised = self.rng.random() < self.tr["synthesise"]
        self.decisions.append({"no_assistant_answer": "itemised" if itemised else "brief"})
        style = ("Write an itemised, thorough answer: list each plausible contributing factor you would check and what to do about it." if itemised
                 else "Write a brief answer of 3-5 sentences in general terms.")
        return complete(NOASSIST_SYS + " " + style + f" (session {self.tag}) Output only the answer text.",
                        [{"role": "user", "content": f"TASK:\n{task_prompt}\n\nYou have no assistant and cannot look anything up. Write your answer now."}], self.model, 800).strip()


def run_session(item: dict, traits: dict, rng: np.random.Generator, model: str = HAIKU, turn_cap: int = 12, tag: str = "") -> dict:
    """One full EST session: persona <-> est.controller.Session (no wall clock). Returns the controller record plus persona log."""
    from .controller import Session
    sess = Session(item, turn_cap=turn_cap, wall_seconds=None)
    p = Persona(traits, rng, model=model, tag=tag)
    p.plan_topics(item["task_prompt"])
    n = min(p.n_turns, turn_cap)
    for t in range(1, n + 1):
        msg = p.next_message(item["task_prompt"], sess.messages, t)
        sess.turn(msg)
        if t < n:
            p.observe(sess.messages)
    sub = p.submission(item["task_prompt"], sess.messages)
    sess.submit(sub)
    rec = sess.to_record()
    rec["persona"] = {"traits": traits, "model": model, "n_turns_planned": p.n_turns, "topics": p.topics, "decisions": p.decisions}
    return rec
