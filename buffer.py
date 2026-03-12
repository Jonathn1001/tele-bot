from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Message:
    channel: str
    text: str
    date: datetime
    sender: str | None = None


class MessageBuffer:
    def __init__(self, maxsize: int = 100) -> None:
        self._maxsize = maxsize
        self._buffers: dict[str, deque[Message]] = {}

    def add(self, channel: str, message: Message) -> None:
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._maxsize)
        self._buffers[channel].append(message)

    def get_all(self, limit: int | None = None) -> list[Message]:
        all_msgs: list[Message] = []
        for buf in self._buffers.values():
            all_msgs.extend(buf)
        all_msgs.sort(key=lambda m: m.date)
        return all_msgs[-limit:] if limit else all_msgs

    def get_channel(self, channel: str, limit: int | None = None) -> list[Message]:
        buf = list(self._buffers.get(channel, []))
        return buf[-limit:] if limit else buf

    def channel_sizes(self) -> dict[str, int]:
        return {ch: len(buf) for ch, buf in self._buffers.items()}

    def is_empty(self) -> bool:
        return all(len(buf) == 0 for buf in self._buffers.values())

    def total_size(self) -> int:
        return sum(len(buf) for buf in self._buffers.values())
