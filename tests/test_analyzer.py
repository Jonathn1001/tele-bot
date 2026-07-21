import os

# Must be set before any project module is imported
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from unittest.mock import MagicMock, patch
from datetime import datetime

import analyzer
from buffer import Message
from notion import Day, Task, Week


def _make_msgs(*texts: str) -> list[Message]:
    return [Message(channel="@ch", text=t, date=datetime.now()) for t in texts]


def _mock_client(response_text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = response_text
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp
    return mock_client


# ---------------------------------------------------------------------------
# Happy path — each function returns the model's .text
# ---------------------------------------------------------------------------

async def test_summarize_returns_model_text():
    msgs = _make_msgs("Event A", "Event B")
    with patch.object(analyzer, "_client", _mock_client("Summary result")):
        result = await analyzer.summarize(msgs)
    assert result == "Summary result"


async def test_assess_threat_returns_model_text():
    msgs = _make_msgs("threat message")
    with patch.object(analyzer, "_client", _mock_client("Threat result")):
        result = await analyzer.assess_threat(msgs)
    assert result == "Threat result"


# ---------------------------------------------------------------------------
# generate_content raises — user gets generic reply, exception detail stays out
# ---------------------------------------------------------------------------

async def test_summarize_failure_returns_generic_error():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.summarize(msgs)
    assert result == analyzer.ANALYSIS_FAILED_REPLY
    assert "API error" not in result


async def test_assess_threat_failure_returns_generic_error():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.assess_threat(msgs)
    assert result == analyzer.ANALYSIS_FAILED_REPLY
    assert "API error" not in result


async def test_fact_check_returns_model_text():
    msgs = _make_msgs("Event A", "Event B")
    with patch.object(analyzer, "_client", _mock_client("SUPPORTED\nEvidence found.")):
        result = await analyzer.fact_check("Russia attacked Ukraine", msgs)
    assert result == "SUPPORTED\nEvidence found."


async def test_fact_check_failure_returns_generic_error():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.fact_check("some claim", msgs)
    assert result == analyzer.ANALYSIS_FAILED_REPLY
    assert "API error" not in result


async def test_fact_check_calls_generate_content_with_search_tool():
    msgs = _make_msgs("msg")
    mock_client = _mock_client("SUPPORTED\nok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.fact_check("some claim", msgs)
    call_kwargs = mock_client.models.generate_content.call_args[1]
    tools = call_kwargs["config"].tools
    assert len(tools) == 1
    assert tools[0].google_search is not None


# ---------------------------------------------------------------------------
# generate_content is called exactly once per invocation
# ---------------------------------------------------------------------------

async def test_generate_content_called_once_per_call():
    msgs = _make_msgs("a", "b", "c")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.summarize(msgs)
    mock_client.models.generate_content.assert_called_once()


# ---------------------------------------------------------------------------
# English-only prompts — analysis commands respond in English; only /paper
# and /thread are Vietnamese (instructions live in system_instruction;
# contents carries only data)
# ---------------------------------------------------------------------------

ENGLISH_ONLY_INSTRUCTION = "Respond in English only."


def _system_instruction(mock_client: MagicMock) -> str:
    return mock_client.models.generate_content.call_args[1]["config"].system_instruction


async def test_summarize_prompt_is_english_only():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.summarize(msgs)
    system = _system_instruction(mock_client)
    assert ENGLISH_ONLY_INSTRUCTION in system
    assert "Tiếng Việt" not in system


async def test_assess_threat_prompt_is_english_only():
    msgs = _make_msgs("threat msg")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.assess_threat(msgs)
    system = _system_instruction(mock_client)
    assert ENGLISH_ONLY_INSTRUCTION in system
    assert "Tiếng Việt" not in system


async def test_fact_check_prompt_is_english_only():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("SUPPORTED\nok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.fact_check("some claim", msgs)
    system = _system_instruction(mock_client)
    assert ENGLISH_ONLY_INSTRUCTION in system
    assert "Tiếng Việt" not in system
    # Single-language response — one verdict at the top of the reply
    assert "Start your response with one of:" in system
    assert "Start each language section with one of:" not in system


# ---------------------------------------------------------------------------
# Prompt-injection hardening — untrusted data is delimited and separated
# from instructions
# ---------------------------------------------------------------------------

async def test_summarize_contents_is_delimited_data_only():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.summarize(msgs)
    contents = mock_client.models.generate_content.call_args[1]["contents"]
    assert contents.startswith("<channel_messages>")
    assert contents.endswith("</channel_messages>")
    assert "Event A" in contents
    assert ENGLISH_ONLY_INSTRUCTION not in contents  # instructions never mix with data


async def test_fact_check_claim_is_delimited():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("SUPPORTED\nok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.fact_check("some claim", msgs)
    contents = mock_client.models.generate_content.call_args[1]["contents"]
    assert "<claim>\nsome claim\n</claim>" in contents
    assert "<channel_messages>" in contents


async def test_system_instruction_marks_data_untrusted():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.summarize(msgs)
    assert analyzer.UNTRUSTED_DATA_NOTICE in _system_instruction(mock_client)


# ---------------------------------------------------------------------------
# Weekly review — code computes the scoreboard; Gemini only narrates
# ---------------------------------------------------------------------------

def test_weekly_scoreboard_collapses_gym_and_buckets_other():
    week = Week(
        label="W",
        days=[
            Day("Mon", [Task("🔥 Chest", True), Task("🔥 Back", False)]),
            Day("Tue", [Task("🔥 Leg", True), Task("🏃 Running", False), Task("misc thing", True)]),
        ],
    )
    total, done, per_cat, per_day = analyzer._weekly_scoreboard(week)
    assert total == 5
    assert done == 3
    assert per_cat["Gym"] == [2, 3]        # 🔥 Chest/Back/Leg → one bucket, 2 of 3 done
    assert per_cat["Running"] == [0, 1]
    assert per_cat["Other"] == [1, 1]      # no known emoji → Other
    assert ("Mon", 1, 2) in per_day


async def test_weekly_review_empty_week_returns_fixed_reply():
    week = Week(label="W", days=[Day("Mon", [])])
    # No Gemini call on the empty path — patch would be unused.
    result = await analyzer.weekly_review(week)
    assert result == analyzer.NO_TASKS_REPLY


async def test_weekly_review_narrates_and_delimits_data():
    week = Week(label="Week X", days=[Day("Mon", [Task("🏃 Running", True)])])
    mock_client = _mock_client("Recap ...")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.weekly_review(week)
    assert result == "Recap ..."
    contents = mock_client.models.generate_content.call_args[1]["contents"]
    assert contents.startswith("<weekly_tasks>")
    assert contents.endswith("</weekly_tasks>")
    assert "🏃 Running" in contents
    system = _system_instruction(mock_client)
    assert "productivity coach" in system
    assert ENGLISH_ONLY_INSTRUCTION in system
    assert analyzer.UNTRUSTED_DATA_NOTICE in system
