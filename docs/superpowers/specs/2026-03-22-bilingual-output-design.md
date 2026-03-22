# Bilingual Output Design

**Date:** 2026-03-22
**Status:** Approved

## Overview

All AI analysis commands (`/summary`, `/threat`, `/factcheck`) will respond in both English and Vietnamese. The change is confined to `analyzer.py`.

## Approach

Append a bilingual instruction to each command's system prompt / inline prompt:

> "Respond in both English and Vietnamese. Label each section clearly — 'English:' then 'Tiếng Việt:'"

## Output Format

```
English:
<response in English>

Tiếng Việt:
<response in Vietnamese>
```

## Affected Code

| Location | Change |
|---|---|
| `analyzer.py` `summarize()` | Append bilingual instruction to system prompt |
| `analyzer.py` `assess_threat()` | Append bilingual instruction to system prompt |
| `analyzer.py` `fact_check()` | Append bilingual instruction to inline prompt |

## Constraints

- Single Gemini API call per command (no extra calls for translation)
- No other files changed
- `fact_check` uses its own inline prompt (bypasses `_ask()`), so it is patched directly
