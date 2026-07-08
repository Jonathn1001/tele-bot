# Bilingual Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All analysis commands (`/summary`, `/threat`, `/factcheck`) respond in both English and Vietnamese.

**Architecture:** Append a bilingual instruction string to each command's system prompt (or inline prompt for `fact_check`). Single Gemini API call per command — no extra translation calls. Only `analyzer.py` and its test file change.

**Tech Stack:** Python, pytest-asyncio, `unittest.mock`

---

### Task 1: Add failing tests for bilingual prompts

**Files:**
- Modify: `tests/test_analyzer.py`

- [ ] **Step 1: Add three failing tests** — one per function, asserting the prompt sent to Gemini contains the bilingual instruction

Open `tests/test_analyzer.py` and add the following tests **after** the existing `test_generate_content_called_once_per_call` test:

```python
# ---------------------------------------------------------------------------
# Bilingual prompts — each function must include the bilingual instruction
# ---------------------------------------------------------------------------

# Full canonical instruction as required by spec — includes the section label requirement
BILINGUAL_INSTRUCTION = "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'"


async def test_summarize_prompt_is_bilingual():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.summarize(msgs)
    prompt = mock_client.models.generate_content.call_args[1]["contents"]
    assert BILINGUAL_INSTRUCTION in prompt


async def test_assess_threat_prompt_is_bilingual():
    msgs = _make_msgs("threat msg")
    mock_client = _mock_client("ok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.assess_threat(msgs)
    prompt = mock_client.models.generate_content.call_args[1]["contents"]
    assert BILINGUAL_INSTRUCTION in prompt


async def test_fact_check_prompt_is_bilingual():
    msgs = _make_msgs("Event A")
    mock_client = _mock_client("SUPPORTED\nok")
    with patch.object(analyzer, "_client", mock_client):
        await analyzer.fact_check("some claim", msgs)
    prompt = mock_client.models.generate_content.call_args[1]["contents"]
    assert BILINGUAL_INSTRUCTION in prompt
    # Verify verdict instruction was updated to place verdict inside each language section
    assert "Start each language section with one of:" in prompt
    assert "Start your response with one of:" not in prompt
```

- [ ] **Step 2: Run the new tests to confirm they fail**

```bash
pytest tests/test_analyzer.py::test_summarize_prompt_is_bilingual \
       tests/test_analyzer.py::test_assess_threat_prompt_is_bilingual \
       tests/test_analyzer.py::test_fact_check_prompt_is_bilingual -v
```

Expected: all 3 FAIL with `AssertionError`

---

### Task 2: Update `analyzer.py` prompts to be bilingual

**Files:**
- Modify: `analyzer.py`

The bilingual instruction to append to `summarize` and `assess_threat`:

```
Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'
```

For `fact_check`, insert it **before** the `f"Channel messages:\n\n{context}"` line so it is not buried after a large context block.

- [ ] **Step 1: Update `summarize()` system prompt**

In `analyzer.py`, change the `summarize()` call from:

```python
async def summarize(messages: list[Message]) -> str:
    return await _ask(
        "You are an intelligence analyst. Extract the 5 most significant events or "
        "developments from these Telegram messages. Be concise and factual. "
        "Format as a numbered list.",
        messages,
    )
```

to:

```python
async def summarize(messages: list[Message]) -> str:
    return await _ask(
        "You are an intelligence analyst. Extract the 5 most significant events or "
        "developments from these Telegram messages. Be concise and factual. "
        "Format as a numbered list. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'",
        messages,
    )
```

- [ ] **Step 2: Update `assess_threat()` system prompt**

Change:

```python
async def assess_threat(messages: list[Message]) -> str:
    return await _ask(
        "Assess the overall threat level and conflict risk based on these Telegram messages. "
        "Rate overall severity 1–5 (1=low, 5=critical). "
        "Explain the top 3 indicators driving your assessment. Be direct.",
        messages,
    )
```

to:

```python
async def assess_threat(messages: list[Message]) -> str:
    return await _ask(
        "Assess the overall threat level and conflict risk based on these Telegram messages. "
        "Rate overall severity 1–5 (1=low, 5=critical). "
        "Explain the top 3 indicators driving your assessment. Be direct. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'",
        messages,
    )
```

- [ ] **Step 3: Update `fact_check()` inline prompt**

Insert the bilingual instruction after the fixed instructions and before the channel messages block. Change:

```python
        "Start your response with one of: SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE. "
        "Then provide a 2-3 sentence explanation citing both channel evidence (channel + timestamp) "
        "and external sources where relevant.\n\n"
        f"Channel messages:\n\n{context}"
```

to:

```python
        "Start each language section with one of: SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE. "
        "Then provide a 2-3 sentence explanation citing both channel evidence (channel + timestamp) "
        "and external sources where relevant. "
        "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'\n\n"
        f"Channel messages:\n\n{context}"
```

- [ ] **Step 4: Run the three new tests to confirm they now pass**

```bash
pytest tests/test_analyzer.py::test_summarize_prompt_is_bilingual \
       tests/test_analyzer.py::test_assess_threat_prompt_is_bilingual \
       tests/test_analyzer.py::test_fact_check_prompt_is_bilingual -v
```

Expected: all 3 PASS

- [ ] **Step 5: Run the full test suite to confirm nothing is broken**

```bash
pytest -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add analyzer.py tests/test_analyzer.py
git commit -m "feat: add bilingual (EN/VI) output to all analysis commands"
```
