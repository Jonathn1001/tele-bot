import asyncio
import logging

from google import genai
from google.genai import types

import config
from buffer import Message

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=config.GEMINI_API_KEY)

# Generic reply for users; real exception goes to the log only so internal
# details (project IDs, quota info, endpoints) never reach Telegram chats.
ANALYSIS_FAILED_REPLY = "Analysis failed. Please try again later."


def _format_messages(messages: list[Message]) -> str:
    lines = []
    for m in messages:
        ts = m.date.strftime("%Y-%m-%d %H:%M")
        sender = f"[{m.sender}]" if m.sender else ""
        lines.append(f"[{ts}] {m.channel} {sender}: {m.text}")
    return "\n".join(lines)


async def _ask(system: str, messages: list[Message]) -> str:
    context = _format_messages(messages)
    prompt = f"{system}\n\nMessages:\n\n{context}"
    try:
        response = await asyncio.to_thread(
            _client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            ),
        )
        return response.text
    except Exception:
        logger.exception("Gemini request failed")
        return ANALYSIS_FAILED_REPLY


async def summarize(messages: list[Message]) -> str:
    return await _ask(
        "You are an intelligence analyst. Extract the 5 most significant events or "
        "developments from these Telegram messages. Be concise and factual. "
        "Format as a numbered list. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'.",
        messages,
    )


async def assess_threat(messages: list[Message]) -> str:
    return await _ask(
        "Assess the overall threat level and conflict risk based on these Telegram messages. "
        "Rate overall severity 1–5 (1=low, 5=critical). "
        "Explain the top 3 indicators driving your assessment. Be direct. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'.",
        messages,
    )


async def fact_check(claim: str, messages: list[Message]) -> str:
    context = _format_messages(messages)
    prompt = (
        f"You are an intelligence analyst. A user has submitted this claim for fact-checking:\n\n"
        f'"{claim}"\n\n'
        "Cross-reference this claim using BOTH the Telegram channel messages below AND "
        "your Google Search grounding to find current, authoritative information.\n\n"
        "Start each language section with one of: SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE. "
        "Then provide a 2-3 sentence explanation citing both channel evidence (channel + timestamp) "
        "and external sources where relevant. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'\n\n"
        f"Channel messages:\n\n{context}"
    )
    try:
        response = await asyncio.to_thread(
            _client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return response.text
    except Exception:
        logger.exception("Gemini fact-check request failed")
        return ANALYSIS_FAILED_REPLY
