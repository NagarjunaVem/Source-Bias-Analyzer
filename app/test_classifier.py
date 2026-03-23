import re
from urllib.parse import urlparse

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


def classify_url(url, text=None):
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]

    score = 0

    # phase 1
    if any(b in segments for b in BAD_SEGMENTS):
        return False

    # phase 2
    if len(segments) >= 4:
        score += 1

    # phase 3
    if segments:
        slug = segments[-1]

        if len(slug) > 40:
            score += 1

        if slug.count("-") >= 4:
            score += 1

    # phase 4
    if any(a in segments for a in ARTICLE_HINTS):
        score += 1

    # phase 5
    if DATE_RE.search(url):
        score += 2

    if LONG_NUM.search(url):
        score += 2

    # phase 6 content length
    if text:
        if len(text) > 1500:
            score += 2
        else:
            score -= 2

    return score >= 4

while(True) :
    url = input("enter url :")
    print(classify_url(url))