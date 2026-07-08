# Bilingual Output Design

**Date:** 2026-03-22
**Status:** Approved

## Overview

All AI analysis commands (`/summary`, `/threat`, `/factcheck`) will respond in both English and Vietnamese. The change is confined to `analyzer.py`.

## Approach

Append a bilingual instruction to each command's system prompt / inline prompt:

> "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'"

## Output Format

**`/summary` and `/threat`:**

```
English:

<response in English>

Tiếng Việt:

<response in Vietnamese>
```

**`/factcheck`** — the existing verdict prefix (`SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE`) must appear inside each language section:

```
English:

SUPPORTED / CONTRADICTED / INSUFFICIENT EVIDENCE
<explanation citing sources>

Tiếng Việt:

<verdict in Vietnamese>
<explanation in Vietnamese>
```

## Affected Code

| Location | Change |
|---|---|
| `analyzer.py` `summarize()` | Append bilingual instruction to system prompt string |
| `analyzer.py` `assess_threat()` | Append bilingual instruction to system prompt string |
| `analyzer.py` `fact_check()` | Insert bilingual instruction **after the fixed instructions and before `f"Channel messages:\n\n{context}"`** — not after the context block |

## Constraints

- Single Gemini API call per command (no extra calls for translation)
- No other files changed
- `fact_check` uses its own inline prompt (bypasses `_ask()`), so it is patched directly
- Response length will roughly double; `bot.py` already chunks responses at 4096 chars so no changes needed there
