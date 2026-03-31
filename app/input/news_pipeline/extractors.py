from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dt_parser


DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
LONG_NUM = re.compile(r"\d{6,}")

BAD_SEGMENTS = {
    "tag",
    "topic",
    "category",
    "search",
    "author",
    "page"
}

ARTICLE_HINTS = {
    "story",
    "article",
    "news",
    "video",
    "liveblog"
}

try:
    import trafilatura
except Exception:  # pragma: no cover - optional dependency
    trafilatura = None

try:
    from readability import Document
except Exception:  # pragma: no cover - optional dependency
    Document = None




NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "button"]

SKIP_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".mp4",
    ".mp3",
    ".pdf",
    ".zip",
    ".css",
    ".js",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
)

STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "at",
    "by",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "that",
    "this",
    "from",
    "about",
    "after",
    "before",
    "over",
    "under",
    "into",
    "their",
    "them",
    "its",
    "will",
    "would",
    "can",
    "could",
    "you",
    "your",
    "our",
    "we",
    "they",
    "he",
    "she",
    "his",
    "her",
    "i",
}


def canonicalize_url(raw_url: str, base_url: str | None = None) -> str:
    if base_url:
        raw_url = urljoin(base_url, raw_url)

    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        return ""

    netloc = parsed.netloc.lower()

    clean_path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/")
    clean_path = clean_path or "/"

    query = parse_qs(parsed.query, keep_blank_values=False)
    kept = []
    for key, values in query.items():
        low = key.lower()
        if low.startswith("utm_") or low in {"gclid", "fbclid", "ocid", "cmpid"}:
            continue
        for value in values:
            kept.append((key, value))
    clean_query = "&".join(f"{k}={v}" for k, v in sorted(kept))

    return urlunparse((parsed.scheme, netloc, clean_path, "", clean_query, ""))


def is_relevant_http_url(url: str) -> bool:
    if not url:
        return False
    low = url.lower()
    if low.startswith(("mailto:", "tel:", "javascript:")):
        return False
    return low.startswith(("http://", "https://"))


#PREVIOUS VERSION (KEPT FOR REFERNCE IN FUTURE)

# def is_probable_article_url(url: str) -> bool:
#     low = url.lower()

#     # ❌ skip non-article files
#     if low.endswith(SKIP_EXTENSIONS):
#         return False

#     # ✅ common article patterns
#     article_tokens = (
#         "/news/",
#         "/article/",
#         "/articles/",
#         "/latest",
#         "/world/",
#         "/india/",
#         "/story",
#         "/stories/",
#     )

#     if any(token in low for token in article_tokens):
#         return True

#     # ✅ date-based URLs
#     return bool(re.search(r"/20\d{2}/\d{1,2}/\d{1,2}/", low))


def is_probable_article_url(url: str, text: str | None = None) -> bool:
    parsed = urlparse(url)

    # 🚫 reject non-http
    if parsed.scheme not in {"http", "https"}:
        return False

    # 🚫 skip static files
    if url.lower().endswith(SKIP_EXTENSIONS):
        return False

    segments = [s for s in parsed.path.split("/") if s]

    score = 0

    # 🔴 phase 1: bad segments
    if any(b in segments for b in BAD_SEGMENTS):
        return False

    # 🟢 phase 2: depth
    if len(segments) >= 3:
        score += 1

    # 🟢 phase 3: slug quality
    if segments:
        slug = segments[-1]

        if len(slug) > 40:
            score += 1

        if slug.count("-") >= 3:
            score += 1

    # 🟢 phase 4: article hints
    if any(a in segments for a in ARTICLE_HINTS):
        score += 1

    # 🟢 phase 5: patterns
    if DATE_RE.search(url):
        score += 2

    if LONG_NUM.search(url):
        score += 1

    # 🟢 phase 6: content length (optional but powerful)
    if text:
        if len(text) > 1500:
            score += 2
        elif len(text) < 300:
            score -= 1

    return score >= 3

def parse_datetime_to_iso(raw_value: object | None) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.isoformat()
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            return dt_parser.parse(raw_value).isoformat()
        except Exception:
            return None
    if hasattr(raw_value, "tm_year"):
        try:
            return datetime(*raw_value[:6]).isoformat()
        except Exception:
            return None
    return None


def extract_links_from_html(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        text = normalize_whitespace(anchor.get_text(" ", strip=True))
        normalized = canonicalize_url(href, base_url=base_url)
        if not normalized or normalized in seen:
            continue
        if not is_relevant_http_url(normalized):
            continue
        seen.add(normalized)
        out.append((normalized, text))
    return out


def parse_rss_entries(feed_text: str) -> list[dict[str, str | None]]:
    feed = feedparser.parse(feed_text)
    rows: list[dict[str, str | None]] = []

    for entry in feed.entries:
        link = canonicalize_url(getattr(entry, "link", ""))
        if not link:
            continue
        title = normalize_whitespace(getattr(entry, "title", "") or "")
        published = (
            parse_datetime_to_iso(getattr(entry, "published", None))
            or parse_datetime_to_iso(getattr(entry, "updated", None))
            or parse_datetime_to_iso(getattr(entry, "published_parsed", None))
            or parse_datetime_to_iso(getattr(entry, "updated_parsed", None))
        )
        rows.append({"url": link, "title": title or None, "published_at": published})

    return rows


def clean_article_html(html: str, base_url: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "lxml")
    for tag in NOISE_TAGS:
        for node in soup.find_all(tag):
            node.decompose()

    headline = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        headline = normalize_whitespace(str(og_title["content"]))
    if not headline and soup.title:
        headline = normalize_whitespace(soup.title.get_text(" ", strip=True))

    candidates: list[tuple[str, str]] = []

    article_root = soup.find("article") or soup.find("main") or soup.body or soup
    candidates.append(("bs4_article_main", _extract_text_from_node(article_root)))

    body = soup.body or soup
    candidates.append(("bs4_body_paragraphs", _extract_text_from_node(body, tags=["p"])))

    if Document is not None:
        try:
            doc = Document(html)
            read_html = doc.summary()
            read_soup = BeautifulSoup(read_html, "lxml")
            read_text = _extract_text_from_node(read_soup)
            if read_text:
                candidates.append(("readability", read_text))
            if not headline:
                read_title = normalize_whitespace(doc.short_title() or "")
                if read_title:
                    headline = read_title
        except Exception:
            pass

    if trafilatura is not None:
        try:
            traf = trafilatura.extract(
                html,
                url=base_url,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
                no_fallback=False,
            )
            if traf:
                candidates.append(("trafilatura", normalize_whitespace(traf)))
        except Exception:
            pass

    method = "none"
    content = ""
    for candidate_method, candidate_text in candidates:
        candidate_text = normalize_whitespace(candidate_text)
        if len(candidate_text) > len(content):
            content = candidate_text
            method = candidate_method

    keyword_tags: list[str] = []
    keywords_meta = soup.find("meta", attrs={"name": "keywords"})
    if keywords_meta and keywords_meta.get("content"):
        keyword_tags = [
            normalize_whitespace(x).lower()
            for x in str(keywords_meta["content"]).split(",")
            if normalize_whitespace(x)
        ]

    links = extract_links_from_html(str(body), base_url=base_url)

    return {
        "headline": headline,
        "content": content,
        "links": links,
        "keyword_tags": keyword_tags,
        "extraction_method": method,
    }


def _extract_text_from_node(node: BeautifulSoup | None, tags: list[str] | None = None) -> str:
    if node is None:
        return ""
    tags = tags or ["h1", "h2", "h3", "p", "li"]
    chunks: list[str] = []
    for item in node.find_all(tags):
        text = normalize_whitespace(item.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        chunks.append(text)
    return dedupe_lines(chunks)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def dedupe_lines(lines: Iterable[str]) -> str:
    seen: set[str] = set()
    clean_lines: list[str] = []
    for line in lines:
        if not line or line in seen:
            continue
        seen.add(line)
        clean_lines.append(line)
    return "\n".join(clean_lines)


def summarize_text(text: str, max_sentences: int = 3, max_chars: int = 600) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    picked = sentences[:max_sentences]
    summary = " ".join(picked).strip()
    if len(summary) > max_chars:
        return summary[: max_chars - 3].rstrip() + "..."
    return summary


def generate_tags(headline: str, content: str, keyword_tags: Iterable[str], max_tags: int = 10) -> list[str]:
    tags: list[str] = []
    for tag in keyword_tags:
        normalized = normalize_whitespace(tag).lower()
        if normalized and normalized not in tags:
            tags.append(normalized)
        if len(tags) >= max_tags:
            return tags

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", f"{headline} {content}".lower())
    filtered = [tok for tok in tokens if tok not in STOP_WORDS]
    top = [tok for tok, _ in Counter(filtered).most_common(max_tags * 2)]
    for tok in top:
        if tok not in tags:
            tags.append(tok)
        if len(tags) >= max_tags:
            break
    return tags
