from dataclasses import dataclass, field
from time import time


@dataclass
class StreamCandidate:
    url: str
    first_seen: float = field(default_factory=time)
    last_seen: float = field(default_factory=time)
    sources: set[str] = field(default_factory=set)
    headers: dict[str, str] = field(default_factory=dict)
    content_type: str | None = None
    content_length: int | None = None


class CandidateStore:
    def __init__(self) -> None:
        self._items: dict[str, StreamCandidate] = {}

    def add_or_update(
        self,
        url: str,
        source: str,
        headers: dict[str, str] | None = None,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> StreamCandidate:
        candidate = self._items.get(url)
        if candidate is None:
            candidate = StreamCandidate(url=url)
            self._items[url] = candidate

        candidate.last_seen = time()
        candidate.sources.add(source)

        if headers:
            for key, value in headers.items():
                if value is None:
                    continue
                key_lower = key.lower()
                candidate.headers[key_lower] = str(value)

        if content_type:
            candidate.content_type = content_type.lower()

        if content_length and content_length > 0:
            candidate.content_length = content_length

        return candidate

    def all(self) -> list[StreamCandidate]:
        return list(self._items.values())

    def urls(self) -> list[str]:
        return list(self._items.keys())
