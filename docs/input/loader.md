# 📄 `loader.py` — Manual Article Text Input

> **Path:** `app/input/loader.py`
> **Role:** Stub utility that reads a raw article text from stdin, used for manual bias classification testing.
> **Pipeline Position:** Outside the automated scraping pipeline — invoked manually for testing.

---

## 📌 Overview

`loader.py` is a **minimal stub** that accepts pasted article text from the terminal. It is **not** part of the automated scraping pipeline but serves as a manual test harness — for example, to test the classifier or bias detection on a custom article.

```python
def load_text():
    print("\nPaste your article below:\n")
    text = input()
    return text.strip()
```

---

## 🔄 Flow

```mermaid
flowchart LR
    A([👤 User]) -->|pastes article text| B[stdin / input]
    B --> C[load_text]
    C -->|returns stripped string| D([Caller / Test Script])

    style A fill:#4CAF50,color:#fff
    style D fill:#2196F3,color:#fff
```

---

## 📖 Function Reference

### `load_text() → str`

| Aspect | Detail |
|--------|--------|
| **Input** | Terminal stdin — user pastes article text |
| **Output** | Stripped string of the pasted text |
| **Side effects** | Prints a prompt to stdout |
| **Error handling** | None — raw `input()` call |

---

## 💡 Example Usage

```python
from app.input.loader import load_text

text = load_text()
# > Paste your article below:
# > [user pastes: "India's economy grew 8.4% in Q3..."]

print(f"Read {len(text)} characters")
# Read 1842 characters
```

---

## ⚠️ Limitations

- Only reads **one line** — multi-line pastes will only capture the first `\n`-terminated chunk depending on terminal behavior.
- No file input support — cannot read from `.txt` or `.json`.
- No encoding handling.

> For production article ingestion, see [`rss_scraper.py`](rss_scraper.md) and [`web_scraper.py`](web_scraper.md).

---

## 🔗 Cross-References

| Reference | Reason |
|-----------|--------|
| [`scraper.py`](scraper.md) | The actual automated pipeline entry point |
| [`rss_scraper.py`](rss_scraper.md) | Production article ingestion via RSS |
| [`web_scraper.py`](web_scraper.md) | Production article ingestion via BFS web crawl |
| [`OVERVIEW.md`](OVERVIEW.md) | Full pipeline context |
