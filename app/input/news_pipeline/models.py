from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FetchTask:
    source_name: str
    source_url: str
    source_type: str
    category: str


@dataclass(slots=True)
class ArticleTask:
    url: str
    source_name: str
    source_type: str
    category: str
    title_hint: str | None = None
    published_at: str | None = None
    depth: int = 0
    discovered_from: str | None = None
    _prefetched: dict | None = None


@dataclass(slots=True)
class DiscoveryTask:
    url: str
    source_name: str
    category: str
    depth: int
    parent_url: str | None = None


@dataclass(slots=True)
class DetailedArticleRecord:
    id: str
    url: str
    title: str
    text: str
    hash: str
    source: str
    published_at: str | None
    language: str
    tags: list[str]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "hash": self.hash,
            "source": self.source,
            "published_at": self.published_at,
            "language": self.language,
            "tags": self.tags,
            "summary": self.summary,
        }
