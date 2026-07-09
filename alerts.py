import re
from dataclasses import dataclass


@dataclass
class Alert:
    channel: str
    text: str
    keywords: list[str]


class AlertMatcher:
    """Matches incoming message text against a keyword watchlist.

    Keywords match case-insensitively on word-ish boundaries, so 'strike'
    won't fire on 'strikeout' but will on 'Strike' or 'air-strike'. An empty
    watchlist disables alerting (matches nothing).
    """

    def __init__(self, keywords: list[str]) -> None:
        self._keywords = [k.strip() for k in keywords if k.strip()]
        if self._keywords:
            # \b around each phrase; phrases may contain spaces (e.g. "martial law").
            alternation = "|".join(re.escape(k) for k in self._keywords)
            self._pattern: re.Pattern[str] | None = re.compile(
                rf"(?<!\w)({alternation})(?!\w)", re.IGNORECASE
            )
        else:
            self._pattern = None

    @property
    def enabled(self) -> bool:
        return self._pattern is not None

    def match(self, text: str) -> list[str]:
        """Distinct keywords (as configured) found in text, preserving watchlist order."""
        if self._pattern is None or not text:
            return []
        found = {m.group(1).lower() for m in self._pattern.finditer(text)}
        return [k for k in self._keywords if k.lower() in found]
