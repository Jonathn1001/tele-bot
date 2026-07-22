# Weekly Review — Write Back to Notion — Design

**Date:** 2026-07-22
**Status:** Approved (brainstorm)
**Repo:** `telegram-intel-bot`
**Supersedes:** the *Out of scope (YAGNI)* bullet "Writing the review text back into
Notion … does not annotate the reviewed week" in
[`2026-07-21-weekly-review-design.md`](2026-07-21-weekly-review-design.md). That
bullet is now **in scope** and is struck in the source spec.

## Goal

After the Sunday weekly review is generated and pushed to Telegram, **append the same
review text back onto the reviewed week's Notion page** so the recap lives with the
tasks it describes. The Telegram push is unchanged; this only adds a Notion write.

## Scope

- **In scope:** append `divider → heading_2 → paragraphs` onto the reviewed week's page,
  from the **scheduled Sunday job only**, **once per page** (skip if a review block
  already exists), gated by a new `WEEKLY_WRITEBACK` flag.
- **Out of scope (YAGNI):** `/weekly` writing back (stays a read-only preview);
  overwriting / refreshing an existing review; a manual "re-persist" escape hatch;
  writing anything other than the review text (no scoreboard tables, no charts);
  top-of-page insertion.

## Why this shape

Reuses the exact conventions the weekly feature already established (`notion.py`):
network I/O and pure parsing/building are split so the block-building is
fixture-testable without a network, and every Notion call **fails soft** — a Notion
outage never crashes the bot. The write is a distinct side-effect isolated from both
the review push (already delivered to Telegram) and the next-week clone.

## Architecture

Edits: `notion.py` (new write path), `main.py` (wire into the Sunday job),
`config.py` + `.env.example` (one flag), `CLAUDE.md` (config table + paragraph),
tests.

### 1. `notion.py` — write path

**Constant**
```python
REVIEW_MARKER = "📝 Weekly Review"   # heading prefix AND the idempotency marker
```

**Pure (fixture-testable, no network)**

- `build_review_blocks(label: str, review_text: str) -> list[dict]`
  Returns `[divider, heading_2, *paragraphs]`:
  - `heading_2` rich text = `f"{REVIEW_MARKER} — {label}"` — built **from the constant**
    so the visible header and the marker can never drift apart.
  - Paragraphs: `_split_paragraphs(review_text)` — split on newlines, strip, **drop
    empty lines**, one paragraph per non-empty line, then hard-chunk any line to
    ≤1900 chars (under Notion's 2000-char rich_text content cap). Splitting per line
    (not per blank-line block) is deliberate: `analyzer.weekly_review` is not
    guaranteed to emit blank-line separators between its four labeled sections or its
    `•` bullets, so a blank-line split could collapse the whole review into one block.
  - Every block is the full create shape: `{"object":"block","type":T,T:{...}}`.
  - Total blocks stay far under the 100-per-request `PATCH` limit (a review is a
    handful of short lines).

- `_has_review_marker(children: list[dict]) -> bool`
  True iff any `heading_2` child's plain text **starts with** `REVIEW_MARKER`
  (label-independent, so it matches regardless of week). Non-`heading_2` blocks and
  headings that merely contain the marker elsewhere are ignored.

**Network**

- `_append_children(client, block_id, blocks)` → `PATCH /blocks/{block_id}/children`
  with `{"children": blocks}`, `raise_for_status()`. Notion appends to the **end** of
  the page (no top-insert without an `after` anchor — accepted; the review lands below
  the trailing "2026 Core Targets" list).

- `append_review(page_id: str, label: str, review_text: str) -> bool`
  ```
  async with _client() as client:
      children = await _get_children(client, page_id)   # flat top-level, paginated
      if _has_review_marker(children):
          logger.info("Notion: review already on %s; skipping write-back", page_id)
          return False
      await _append_children(client, page_id, build_review_blocks(label, review_text))
  return True
  ```
  **Raises** on network error (caller catches) — same contract as `create_next_week`.
  Returns `True` when written, `False` when skipped. `_get_children` already follows
  `next_cursor`, so the marker is found even on a >100-block page.

### 2. `main.run_weekly_review` — wire into the Sunday job

Inserted as a `try/else` on the existing review block so `text` is defined and the
write only runs after a *successful, meaningful* review:

```python
else:
    if config.WRITEBACK_ENABLED and text not in (
        analyzer.NO_TASKS_REPLY, analyzer.ANALYSIS_FAILED_REPLY
    ):
        try:
            await notion.append_review(page.id, week.label, text)
        except Exception:
            logger.exception("weekly: append_review failed")
            # review already delivered to Telegram — log only, no owner notice
```

- **Placeholder guard:** `weekly_review` returns `NO_TASKS_REPLY` for an empty week and
  `ANALYSIS_FAILED_REPLY` when Gemini errors (it catches, doesn't raise). Neither is
  worth persisting — comparing against those two module constants is the single source
  of "don't write" (no re-derived emptiness check).
- **Isolation:** write-back sits inside the review branch and never touches the
  next-week clone (which runs after, unchanged) or the review push.
- **Failure policy — intentional asymmetry:** unlike `create_next_week` (which sends a
  `⚠️` owner notice), a write-back failure is **log-only**. The owner already has the
  review in Telegram; a Notion-persistence miss is not owner-actionable, so no extra
  message.
- `/weekly` command is **unchanged** — read-only preview, no Notion write.

### 3. `config.py` — one flag (mirrors `WEEKLY_AUTOCREATE`)

```python
_WEEKLY_WRITEBACK_RAW = os.environ.get("WEEKLY_WRITEBACK", "true").strip().lower()
WEEKLY_WRITEBACK = _WEEKLY_WRITEBACK_RAW not in ("0", "false", "no", "off", "")
WRITEBACK_ENABLED = bool(WEEKLY_ENABLED and WEEKLY_WRITEBACK)
```
Default **on**; `WEEKLY_WRITEBACK=false` keeps Telegram-only. Needs no new credential —
it writes to the page already located by the review. Added to `.env.example` and the
`CLAUDE.md` config table + the weekly architecture paragraph.

## Testing

`tests/test_notion.py` (pure + mocked network):
- `build_review_blocks`: emits `divider` + `heading_2` (text == `f"{REVIEW_MARKER} — …"`)
  + one paragraph per non-empty line; blank lines dropped; a >1900-char line
  hard-chunked into multiple paragraphs; every block has the `{"object":"block", ...}`
  shape.
- `_has_review_marker`: `heading_2` starting with `REVIEW_MARKER` → True; absent → False;
  a `heading_1`/`paragraph` with the same text → ignored (only `heading_2` counts).
- `append_review` idempotency: mocked `_get_children` returns a marker → returns `False`
  and the `PATCH` is **not** issued (mock asserts not awaited); no marker → `PATCH`
  awaited once with the built blocks, returns `True`.
- Soft-fail: network error inside `append_review` propagates (caller catches).

`tests/test_weekly_job.py`:
- Happy path: successful review → `append_review` awaited once with `(page.id, week.label, text)`.
- `append_review` raising does **not** lose the review push and does **not** block the clone.
- No write when `WRITEBACK_ENABLED` is false, or when `text` is `NO_TASKS_REPLY` /
  `ANALYSIS_FAILED_REPLY`.

## Security notes

Posture unchanged from the weekly feature: client pinned to `api.notion.com`; the
page id comes only from the already-located week page (never user input); the review
text is our own model output (not untrusted channel data); `NOTION_API_KEY` stays in
`.env` and is never logged (errors log page ids / status codes only — satisfies
`.claude/rules/sensitive-logging.md`). Write scope is a single `PATCH …/children`
append on the reviewed page; it never edits or deletes existing blocks.

## Resolved / open

- **Skip-once (resolved, accepted):** a first bad/truncated review is never
  auto-corrected — chosen over overwrite for simplicity. Manual re-persist is out of
  scope.
- **Bottom placement (resolved, accepted):** Notion append has no top-insert without an
  `after` anchor; the review sits at the page end.
- **`WEEKLY_WRITEBACK` flag (resolved, kept):** mirrors `WEEKLY_AUTOCREATE` for
  reversibility even though write-back is intrinsic to the Sunday review.
