"""Shared constants for retrieval ranking and scoring."""

TOP_K_FAISS = 8
TOP_K_BM25 = 8
TOP_K_PER_SITE = 5
TOP_K_COMBINED = 30
TOP_K_FINAL_MIN = 10
TOP_K_FINAL_MAX = 15
DEFAULT_CREDIBILITY = 0.60

CREDIBILITY_SCORES = {
    "reuters_com": 1.00,
    "apnews_com": 1.00,
    "bbc_com": 0.95,
    "bbc_co_uk": 0.95,
    "theguardian_com": 0.90,
    "npr_org": 0.90,
    "nature_com": 0.95,
    "sciencedaily_com": 0.88,
    "aljazeera_com": 0.82,
    "cnbc_com": 0.82,
    "techcrunch_com": 0.80,
    "wired_com": 0.80,
    "arstechnica_com": 0.80,
    "theverge_com": 0.78,
    "engadget_com": 0.75,
    "indianexpress_com": 0.75,
    "thehindu_com": 0.75,
    "hindustantimes_com": 0.70,
    "timesofindia_indiatimes_com": 0.68,
    "indiatoday_in": 0.68,
    "livemint_com": 0.68,
    "artificialintelligence_news_com": 0.65,
    "aajtak_in": 0.60,
    "space_com": 0.75,
}
