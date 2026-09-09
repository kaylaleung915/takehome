"""LLM-driven synthetic participants. They see ONLY the task prompt and the visible transcript."""
from __future__ import annotations
from .llm import complete, HAIKU

POLICIES = {
 "WEAK": {"max_turns": 2, "style": """You are simulating a LOW-skill participant. Behaviour rules:
- Turn 1: ask ONE broad question that basically restates the task ("why might this be happening / what should we watch out for?").
- Turn 2 (optional): one short generic follow-up like "anything else?" or "ok thanks, what should we do?". Do not ask for records, logs, numbers or specifics.
- Never question numbers you are given. Then you are done."""},
 "MEDIUM": {"max_turns": 6, "style": """You are simulating a MID-skill participant. Behaviour rules:
- Break the problem into the 4-6 most likely categories and ask about ONE category per turn, in plain terms (e.g. "could it be the equipment?", "what about the ingredients?").
- Accept whatever answer you get and move on to the next category; do NOT re-ask, do NOT demand logs/readings/numbers, do NOT push if told there's no record.
- Do not scrutinise numbers or dates you are given. Stop when categories are covered or turns run out."""},
 "STRONG": {"max_turns": 10, "style": """You are simulating a HIGH-skill participant. Behaviour rules:
- First, enumerate every plausible category of situation-specific cause/issue. Then, one or two per turn, ask for the CONCRETE RECORDS: measurements, readings, log entries, saved settings, dates, edit histories, notices, staff/other-user reports.
- If the assistant answers vaguely, gives only generic advice, or says it sees no record, re-ask on a later turn more pointedly and more specifically (name the exact record you want). Do this at least once for anything unanswered, including "has anyone else reported problems / any other notes or reports?".
- Scrutinise every number, date, time and unit the assistant gives you; do the arithmetic; if two facts don't reconcile, say so explicitly and ask it to double-check.
- Keep a running list; use your last available turn to ask for anything still missing."""},
}

SUBMIT_SYS = {
 "WEAK": "Write the participant's final submission: 3-5 sentences summarising what the assistant said, in general terms. Do not add facts that were not in the conversation.",
 "MEDIUM": "Write the participant's final submission: a short structured summary (bullets) of what was learned per category. Do not add facts that were not in the conversation.",
 "STRONG": "Write the participant's final submission: an itemised list of EVERY situation-specific fact learned (with the exact numbers/dates), each with a recommended action, plus a section 'Inconsistencies noticed' if any. Do not add facts that were not in the conversation.",
}


def next_message(policy: str, task_prompt: str, transcript: list[dict], turn_idx: int, max_turns: int, nonce: str) -> str:
    p = POLICIES[policy]
    sys = (f"{p['style']}\n\nYou are the PARTICIPANT talking to an assistant. Output ONLY your next chat message (1-4 sentences, no role labels, no meta-commentary). "
           f"This is your turn {turn_idx} of at most {max_turns}. Session nonce: {nonce}.")
    convo = "\n".join(f"{'YOU' if m['role']=='user' else 'ASSISTANT'}: {m['content']}" for m in transcript) or "(conversation not started)"
    user = f"TASK:\n{task_prompt}\n\nCONVERSATION SO FAR:\n{convo}\n\nWrite your next message."
    return complete(sys, [{"role": "user", "content": user}], HAIKU, 300).strip()


def submission(policy: str, task_prompt: str, transcript: list[dict], nonce: str) -> str:
    convo = "\n".join(f"{'YOU' if m['role']=='user' else 'ASSISTANT'}: {m['content']}" for m in transcript)
    sys = SUBMIT_SYS[policy] + f" Session nonce: {nonce}. Output only the submission text."
    return complete(sys, [{"role": "user", "content": f"TASK:\n{task_prompt}\n\nCONVERSATION:\n{convo}\n\nWrite the submission now."}], HAIKU, 700).strip()
