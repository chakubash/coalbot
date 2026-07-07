
from dataclasses import dataclass
from typing import Optional


@dataclass
class ArticleCandidate:
    source: str
    title: str
    url: str
    context_text: str = ""
    list_published_at: Optional[str] = None


@dataclass
class Article:
    source: str
    title: str
    url: str
    content: str
    published_at: Optional[str]
    language: str
    raw_html: str = ""
    published_at_raw: str = ""
