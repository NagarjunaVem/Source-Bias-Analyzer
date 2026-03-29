import streamlit as st
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import os
import sys

# ensure local modules are found
sys.path.append(os.path.dirname(__file__))

from app.analysis.bias_detector import analyze_bias
from app.retrieval.faiss_retriever import search

# base directory
BASE_DIR = os.path.dirname(__file__)

# faiss paths
INDEX_PATH = os.path.join(BASE_DIR, "app/embeddings/vector_index/articles.index")
CHUNKS_PATH = os.path.join(BASE_DIR, "app/embeddings/vector_index/metadata.json")


# extract text from url
def extract_text_from_url(url: str) -> str:
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "lxml")
        return " ".join(p.get_text() for p in soup.find_all("p")).strip()
    except Exception as e:
        return f"Error fetching URL: {e}"


# extract text from pdf
def extract_text_from_pdf(file) -> str:
    text = ""
    with fitz.open(stream=file.read(), filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()
    return text


# build rag context
def build_context(results, max_chars=3000):
    chunks = []
    for r in results:
        text = r.get("text", "")[:800]
        url = r.get("url", "unknown")
        chunks.append(f"[Source: {url}]\n{text}")
    return "\n\n".join(chunks)[:max_chars]


# pipeline
def run_pipeline(article_text):
    results = search(article_text, INDEX_PATH, CHUNKS_PATH, top_k=5)
    context = build_context(results) if results else ""

    combined = f"""
    INPUT ARTICLE:
    {article_text}

    RELATED SOURCES:
    {context}
    """

    output = analyze_bias(combined)
    return output, results


# ui config
st.set_page_config(page_title="Source Bias Analyzer", layout="wide")

# title
st.title("Source Bias Analyzer")

# input selector
input_type = st.selectbox("Input Type", ["Text", "URL", "PDF"])

article_text = ""


# text input
if input_type == "Text":
    article_text = st.text_area("Input Text", height=300)

# url input
elif input_type == "URL":
    url = st.text_input("Article URL")
    if st.button("Load URL"):
        with st.spinner("Fetching content"):
            article_text = extract_text_from_url(url)

# pdf input
elif input_type == "PDF":
    file = st.file_uploader("Upload PDF", type=["pdf"])
    if file:
        with st.spinner("Extracting text"):
            article_text = extract_text_from_pdf(file)


# preview
if article_text:
    st.subheader("Extracted Content")
    st.text_area("", article_text[:3000], height=200)


# run analysis
if st.button("Run Analysis"):
    if not article_text:
        st.warning("No input provided")
    else:
        with st.spinner("Running pipeline"):
            output, results = run_pipeline(article_text)

        st.subheader("Analysis Output")
        st.json(output)

        if results:
            st.subheader("Retrieved Sources")
            for r in results:
                st.markdown(f"**Title:** {r.get('title')}")
                st.markdown(f"**Score:** {r.get('score'):.3f}")
                st.markdown(f"**URL:** {r.get('url')}")
                st.markdown("---")