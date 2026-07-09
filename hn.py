import re
import time
from dataclasses import dataclass

import aiohttp

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"

# Title filter for the security digest; tune here, no config knob needed.
SECURITY_PATTERN = re.compile(
    r"\b(?:"
    r"security|vulnerabilit\w*|cve[- ]?\d*|exploit\w*|breach\w*|hacked|hacker\w*"
    r"|malware|ransomware|zero[- ]day|0[- ]day|backdoor\w*|phishing|leak\w*"
    r"|botnet|spyware|rootkit|xss|sql injection|rce|infosec|cyberattack\w*"
    r"|cybersecurity|credential\w*|ddos|mitm|supply[- ]chain attack|encryption"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class Story:
    title: str
    url: str
    points: int
    comments: int
    hn_url: str


def filter_stories(hits: list[dict], limit: int = 12) -> list[Story]:
    """Keep security-related stories, best first."""
    matched = [
        h for h in hits
        if h.get("title") and SECURITY_PATTERN.search(h["title"])
    ]
    matched.sort(key=lambda h: h.get("points") or 0, reverse=True)
    stories = []
    for h in matched[:limit]:
        hn_url = f"https://news.ycombinator.com/item?id={h.get('objectID', '')}"
        stories.append(Story(
            title=h["title"],
            url=h.get("url") or hn_url,
            points=h.get("points") or 0,
            comments=h.get("num_comments") or 0,
            hn_url=hn_url,
        ))
    return stories


async def fetch_security_stories(window_hours: int = 13, limit: int = 12) -> list[Story]:
    cutoff = int(time.time()) - window_hours * 3600
    params = {
        "tags": "story",
        "hitsPerPage": 1000,
        "numericFilters": f"created_at_i>{cutoff}",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(ALGOLIA_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return filter_stories(data.get("hits", []), limit=limit)
