CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE,
    title TEXT,
    content TEXT,
    summary TEXT,
    source TEXT,
    published_at DATE,
    language TEXT,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_url ON articles(url);