import os

# Must be set before any project module is imported
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")

from unittest.mock import MagicMock, patch
from datetime import datetime

import analyzer
from buffer import Message


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
# generate_content raises — result starts with "Analysis failed:"
# ---------------------------------------------------------------------------

async def test_summarize_failure_returns_error_string():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.summarize(msgs)
    assert result.startswith("Analysis failed:")


async def test_assess_threat_failure_returns_error_string():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.assess_threat(msgs)
    assert result.startswith("Analysis failed:")


async def test_fact_check_returns_model_text():
    msgs = _make_msgs("Event A", "Event B")
    with patch.object(analyzer, "_client", _mock_client("SUPPORTED\nEvidence found.")):
        result = await analyzer.fact_check("Russia attacked Ukraine", msgs)
    assert result == "SUPPORTED\nEvidence found."


async def test_fact_check_failure_returns_error_string():
    msgs = _make_msgs("msg")
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API error")
    with patch.object(analyzer, "_client", mock_client):
        result = await analyzer.fact_check("some claim", msgs)
    assert result.startswith("Analysis failed:")


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
