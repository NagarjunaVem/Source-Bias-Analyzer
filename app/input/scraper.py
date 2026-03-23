import requests
from bs4 import BeautifulSoup
import time

BASE_URL = "https://www.hindustantimes.com"
START_URL = "https://www.hindustantimes.com/latest-news"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

visited = set()


def get_article_links(url):
    """Extract article links from a listing page"""
    links = []
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")

        for a in soup.find_all("a", href=True):
            link = a["href"]

            if link.startswith("/"):
                link = BASE_URL + link

            # filter news articles
            if BASE_URL in link and "-" in link:
                links.append(link)

    except Exception as e:
        print("Error fetching links:", e)

    return list(set(links))


def scrape_article(url):
    """Extract full article content"""
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")

        # Title
        title = soup.find("h1")
        title = title.get_text(strip=True) if title else "No Title"

        # Article paragraphs
        paragraphs = soup.find_all("p")
        content = "\n".join([p.get_text(strip=True) for p in paragraphs])

        print("=" * 80)
        print("TITLE:", title)
        print("URL:", url)
        print("\nCONTENT:\n", content[:2000])  # limit to avoid overload
        print("=" * 80)

    except Exception as e:
        print("Error scraping article:", url, e)


def crawl(pages=5):
    """Crawl multiple pages"""
    for page in range(1, pages + 1):
        print(f"\n--- Scraping page {page} ---\n")

        url = f"{START_URL}/page-{page}"
        links = get_article_links(url)

        for link in links:
            if link not in visited:
                visited.add(link)
                scrape_article(link)
                time.sleep(1)  # avoid blocking


if __name__ == "__main__":
    crawl(pages=5)  # increase pages for more coverage