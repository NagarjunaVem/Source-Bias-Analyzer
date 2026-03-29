import os
import sys
import time
from typing import Any

os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

import streamlit as st
import requests
from bs4 import BeautifulSoup

try:
    import pymupdf as fitz  # PyMuPDF
except ImportError:
    fitz = None

# ensure local modules are found
sys.path.append(os.path.dirname(__file__))

from app.analysis.bias_detector import analyze_bias
from app.analysis.scorer import score_article
from app.retrieval.faiss_retriever import search

# base directory
BASE_DIR = os.path.dirname(__file__)

# faiss paths
INDEX_BASE_DIR = os.path.join(BASE_DIR, "app/embeddings/vector_index")

STANCE_COLORS = {
    "SUPPORT": "#1f7a4f",
    "CONTRADICT": "#b42318",
    "NEUTRAL": "#667085",
}


# extract text from url
def extract_text_from_url(url: str) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return "Error fetching URL: invalid URL"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        return " ".join(p.get_text() for p in soup.find_all("p")).strip()
    except Exception as e:
        return f"Error fetching URL: {e}"


# extract text from pdf
def extract_text_from_pdf(file) -> str:
    if fitz is None:
        return "Error reading PDF: PyMuPDF is not available in this environment"
    text = ""
    try:
        with fitz.open(stream=file.read(), filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        return f"Error reading PDF: {e}"
    return text


class StreamlitLogWriter:
    """Capture print output and mirror it into a Streamlit placeholder."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._partial = ""

    def write(self, value: str) -> int:
        if not value:
            return 0
        self._partial += value
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            if line.strip():
                self.lines.append(line)
        return len(value)

    def flush(self) -> None:
        if self._partial.strip():
            self.lines.append(self._partial)
            self._partial = ""

    def get_value(self) -> str:
        self.flush()
        return "\n".join(self.lines)


def run_pipeline(article_text: str, log_placeholder):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    log_writer = StreamlitLogWriter()
    started_at = time.time()
    log_placeholder.code("Starting retrieval for the input article...", language="text")
    try:
        sys.stdout = log_writer
        sys.stderr = log_writer
        print("Starting retrieval for the input article...")
        results = search(article_text, INDEX_BASE_DIR, top_k=6)
        log_placeholder.code(log_writer.get_value() or "Retrieval finished.", language="text")
        print("Running claim verification, contradiction detection, and scoring...")
        log_placeholder.code(
            (log_writer.get_value() + "\nRunning claim verification, contradiction detection, and scoring...").strip(),
            language="text",
        )
        output = analyze_bias(article_text, retrieval_base_dir=INDEX_BASE_DIR)
        evidence_text = "\n\n".join(
            f"Source: {item.get('website_name', 'Unknown')} | Title: {item.get('title', 'Untitled')} | URL: {item.get('url', '')}"
            for item in results[:8]
        )
        print("Running calibrated score model...")
        calibrated_scores = score_article(article_text, evidence=evidence_text)
        print(f"Completed in {time.time() - started_at:.1f}s.")
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
    final_logs = log_writer.get_value()
    log_placeholder.code(final_logs or "No logs captured.", language="text")
    return output, results, final_logs, calibrated_scores


def render_score_card(title: str, value: float, inverse: bool = False) -> None:
    """Render one score with a progress bar."""
    normalized_value = max(0.0, min(1.0, float(value)))
    display_value = 1.0 - normalized_value if inverse else normalized_value
    st.markdown(f"**{title}**")
    st.progress(display_value)
    st.caption(f"{display_value:.2f}")


def render_pie_chart(title: str, items: list[dict[str, Any]], color_field: str = "color") -> None:
    """Render a simple pie chart with Vega-Lite."""
    if not items:
        st.info(f"No data available for {title.lower()}.")
        return
    st.markdown(f"**{title}**")
    st.vega_lite_chart(
        {
            "data": {"values": items},
            "mark": {"type": "arc", "outerRadius": 90},
            "encoding": {
                "theta": {"field": "value", "type": "quantitative"},
                "color": {"field": "label", "type": "nominal", "scale": {"range": [item[color_field] for item in items]}},
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "value", "type": "quantitative"},
                ],
            },
            "view": {"stroke": None},
        },
        use_container_width=True,
    )


def render_bar_chart(title: str, items: list[dict[str, Any]], color: str = "#3b82f6") -> None:
    """Render a simple bar chart with Vega-Lite."""
    if not items:
        st.info(f"No data available for {title.lower()}.")
        return
    st.markdown(f"**{title}**")
    st.vega_lite_chart(
        {
            "data": {"values": items},
            "mark": {"type": "bar", "cornerRadiusTopLeft": 6, "cornerRadiusTopRight": 6, "color": color},
            "encoding": {
                "x": {"field": "label", "type": "nominal", "axis": {"labelAngle": 0, "title": ""}},
                "y": {"field": "value", "type": "quantitative", "scale": {"domain": [0, 1]}, "title": ""},
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "value", "type": "quantitative", "format": ".2f"},
                ],
            },
            "view": {"stroke": None},
        },
        use_container_width=True,
    )


def render_claim_analysis(claim_analysis: list[dict[str, Any]]) -> None:
    for item in claim_analysis:
        stance = str(item.get("stance", "NEUTRAL"))
        color = STANCE_COLORS.get(stance, STANCE_COLORS["NEUTRAL"])
        with st.expander(f"{stance}: {item.get('claim', '')}", expanded=False):
            st.markdown(
                f"<div style='padding:0.6rem 0.8rem;border-left:6px solid {color};background:#f8fafc;'>"
                f"<strong>Confidence:</strong> {item.get('stance_confidence', 0.0):.2f}<br>"
                f"<strong>Support:</strong> {item.get('support_count', 0)} | "
                f"<strong>Contradict:</strong> {item.get('contradict_count', 0)} | "
                f"<strong>Neutral:</strong> {item.get('neutral_count', 0)}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown("**Evidence Sources**")
            evidence_items = item.get("evidence", [])
            if not evidence_items:
                st.caption("No strong linked sources were found for this claim.")
            for evidence in evidence_items:
                source = evidence.get("source", "Unknown")
                title = evidence.get("title", "Untitled")
                url = evidence.get("url", "")
                published_at = evidence.get("published_at", "")
                if url:
                    st.markdown(f"- [{source} | {title}]({url})")
                else:
                    st.markdown(f"- {source} | {title}")
                if published_at:
                    st.caption(published_at)


def render_biased_language(highlights: list[dict[str, str]]) -> None:
    if not highlights:
        st.info("No strongly biased wording was flagged by the lexical detector.")
        return
    for item in highlights:
        st.markdown(f"**Terms:** {item.get('terms', '')}")
        st.write(item.get("text", ""))


def render_source_table(results: list[dict[str, Any]]) -> None:
    if not results:
        st.warning("No retrieval results were found for this article.")
        return
    for result in results:
        source_name = result.get("website_name", "Unknown")
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        score = float(result.get("score", 0.0))
        if url:
            st.markdown(f"**[{title}]({url})**")
        else:
            st.markdown(f"**{title}**")
        st.caption(f"{source_name} | Score: {score:.3f}")
        st.markdown("---")


def render_contradictions(contradictions: list[dict[str, Any]]) -> None:
    """Render contradictions as visual cards."""
    if not contradictions:
        st.info("No explicit cross-source contradictions were detected.")
        return
    for item in contradictions:
        contradiction_type = str(item.get("type", "narrative")).title()
        sources = ", ".join(item.get("sources", []))
        st.markdown(
            f"<div style='padding:0.8rem 1rem;border:1px solid #fecaca;border-radius:12px;"
            f"background:#fff1f2;margin-bottom:0.75rem;'>"
            f"<strong>{contradiction_type} Contradiction</strong><br>"
            f"{item.get('claim', '')}<br>"
            f"<span style='color:#b42318;'>Sources: {sources}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_narrative_section(narrative_analysis: dict[str, Any]) -> None:
    """Render narrative findings without JSON."""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Article Narrative**")
        st.write(narrative_analysis.get("article_narrative", ""))
        st.markdown("**Framing Bias**")
        st.write(narrative_analysis.get("framing_bias", ""))
    with col2:
        st.markdown("**Selective Emphasis**")
        st.write(narrative_analysis.get("selective_emphasis", ""))
        st.markdown("**Source Narratives**")
        for item in narrative_analysis.get("source_narratives", []):
            st.markdown(f"- **{item.get('source', 'Unknown')}**: {item.get('summary', '')}")


def render_missing_viewpoints(missing_viewpoints: dict[str, Any]) -> None:
    """Render missing-viewpoint analysis visually."""
    st.markdown("**Coverage Balance**")
    clusters = missing_viewpoints.get("clusters", {})
    for label, value in clusters.items():
        st.write(f"{label.title()}: {value}")
    missing = missing_viewpoints.get("missing", [])
    if missing:
        st.warning("Missing perspectives: " + ", ".join(missing))
    else:
        st.success("No major viewpoint gap was flagged.")


def render_simple_summary(output: dict[str, Any]) -> None:
    """Explain the result in plain language."""
    scores = output.get("scores", {})
    factual_accuracy = float(scores.get("factual_accuracy", 0.0))
    narrative_bias = float(scores.get("narrative_bias", 0.0))
    completeness = float(scores.get("completeness", 0.0))

    if factual_accuracy >= 0.7 and narrative_bias <= 0.35:
        summary = "This article appears mostly supported by the available sources, with comparatively lower framing bias."
    elif factual_accuracy <= 0.4 or narrative_bias >= 0.65:
        summary = "This article shows strong signs of weak support or heavy framing, so it should be treated carefully."
    else:
        summary = "This article has mixed signals: some parts line up with other sources, but the framing or coverage may still be uneven."

    if completeness < 0.5:
        summary += " Important viewpoints may also be missing."

    st.info(summary)


def build_claim_stance_chart_data(claim_analysis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build chart data for claim stance distribution."""
    counts = {"Support": 0, "Contradict": 0, "Neutral": 0}
    for item in claim_analysis:
        stance = str(item.get("stance", "NEUTRAL")).upper()
        if stance == "SUPPORT":
            counts["Support"] += 1
        elif stance == "CONTRADICT":
            counts["Contradict"] += 1
        else:
            counts["Neutral"] += 1
    return [
        {"label": "Support", "value": counts["Support"], "color": "#1f7a4f"},
        {"label": "Contradict", "value": counts["Contradict"], "color": "#b42318"},
        {"label": "Neutral", "value": counts["Neutral"], "color": "#667085"},
    ]


def build_score_chart_data(scores: dict[str, Any]) -> list[dict[str, Any]]:
    """Build chart data for score summary."""
    return [
        {"label": "Factual", "value": float(scores.get("factual_accuracy", 0.0))},
        {"label": "Completeness", "value": float(scores.get("completeness", 0.0))},
        {"label": "Confidence", "value": float(scores.get("confidence", 0.0))},
        {"label": "Bias Risk", "value": 1.0 - float(scores.get("narrative_bias", 0.0))},
    ]


def build_source_chart_data(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build chart data for source distribution."""
    counts: dict[str, int] = {}
    for result in results:
        label = str(result.get("website_name", "Unknown"))
        counts[label] = counts.get(label, 0) + 1
    return [{"label": key, "value": value} for key, value in counts.items()]


def build_credibility_chart_data(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build chart data for source credibility scores."""
    aggregated: dict[str, list[float]] = {}
    for result in results:
        label = str(result.get("website_name", "Unknown"))
        aggregated.setdefault(label, []).append(float(result.get("credibility_score", 0.0)))
    return [
        {"label": label, "value": round(sum(values) / max(len(values), 1), 4)}
        for label, values in aggregated.items()
    ]


def build_calibrated_score_chart_data(calibrated_scores: dict[str, Any]) -> list[dict[str, Any]]:
    """Build chart data from score.py outputs."""
    if not calibrated_scores:
        return []
    return [
        {"label": "Credibility", "value": float(calibrated_scores.get("credibility_score", 0.0))},
        {"label": "Completeness", "value": float(calibrated_scores.get("completeness_score", 0.0))},
        {"label": "Bias Control", "value": 1.0 - float(calibrated_scores.get("bias_score", 0.0))},
        {"label": "Confidence", "value": float(calibrated_scores.get("confidence", 0.0))},
    ]


def render_calibrated_score_section(calibrated_scores: dict[str, Any]) -> None:
    """Render additional calibrated scores from score.py."""
    if not calibrated_scores:
        return
    st.subheader("Calibrated Score View")
    cols = st.columns(4)
    cols[0].metric("Credibility", f"{float(calibrated_scores.get('credibility_score', 0.0)):.2f}")
    cols[1].metric("Bias Score", f"{float(calibrated_scores.get('bias_score', 0.0)):.2f}")
    cols[2].metric("Completeness", f"{float(calibrated_scores.get('completeness_score', 0.0)):.2f}")
    cols[3].metric("Confidence", f"{float(calibrated_scores.get('confidence', 0.0)):.2f}")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        render_bar_chart("Calibrated Score Graph", build_calibrated_score_chart_data(calibrated_scores), color="#8b5cf6")
    with chart_col2:
        component_scores = calibrated_scores.get("component_scores", {})
        component_items = [
            {"label": key.replace("_", " ").title(), "value": float(value)}
            for key, value in component_scores.items()
        ]
        render_bar_chart("Detailed Component Scores", component_items, color="#f59e0b")

    explanation = str(calibrated_scores.get("explanation", "")).strip()
    if explanation:
        st.caption(explanation)


# ui config
st.set_page_config(page_title="Source Bias Analyzer", layout="wide")

# title
st.title("Evidence-Based News Bias Analyzer")

if "article_text" not in st.session_state:
    st.session_state.article_text = ""
if "analysis_output" not in st.session_state:
    st.session_state.analysis_output = None
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = []
if "analysis_logs" not in st.session_state:
    st.session_state.analysis_logs = ""
if "last_analyzed_text" not in st.session_state:
    st.session_state.last_analyzed_text = ""
if "calibrated_scores" not in st.session_state:
    st.session_state.calibrated_scores = {}

# input selector
input_type = st.selectbox("Input Type", ["Text", "URL", "PDF"])

article_text = ""


# text input
if input_type == "Text":
    article_text = st.text_area("Input Text", value=st.session_state.article_text, height=300)
    st.session_state.article_text = article_text

# url input
elif input_type == "URL":
    url = st.text_input("Article URL")
    if st.button("Load URL"):
        with st.spinner("Fetching content"):
            st.session_state.article_text = extract_text_from_url(url)
    article_text = st.session_state.article_text

# pdf input
elif input_type == "PDF":
    file = st.file_uploader("Upload PDF", type=["pdf"])
    if fitz is None:
        st.warning("PDF support is currently unavailable because PyMuPDF could not be imported.")
    if file:
        with st.spinner("Extracting text"):
            st.session_state.article_text = extract_text_from_pdf(file)
    article_text = st.session_state.article_text


# preview
if article_text:
    st.subheader("Extracted Content")
    st.text_area("Extracted article preview", article_text[:3000], height=200, label_visibility="collapsed")

live_logs_container = st.empty()


# run analysis
if st.button("Run Analysis"):
    if not article_text:
        st.warning("No input provided")
    else:
        try:
            output, results, logs, calibrated_scores = run_pipeline(article_text, live_logs_container)
        except ValueError as error:
            st.error(str(error))
            st.stop()
        st.session_state.analysis_output = output
        st.session_state.analysis_results = results
        st.session_state.analysis_logs = logs
        st.session_state.calibrated_scores = calibrated_scores
        st.session_state.last_analyzed_text = article_text

if st.session_state.analysis_output and st.session_state.last_analyzed_text == article_text:
        output = st.session_state.analysis_output
        results = st.session_state.analysis_results
        logs = st.session_state.analysis_logs
        calibrated_scores = st.session_state.calibrated_scores

        live_logs_container.code(logs or "No logs captured.", language="text")

        scores = output.get("scores", {})
        st.subheader("Simple Summary")
        render_simple_summary(output)

        st.subheader("Score Overview")
        score_cols = st.columns(4)
        with score_cols[0]:
            render_score_card("Factual Accuracy", scores.get("factual_accuracy", 0.0))
        with score_cols[1]:
            render_score_card("Narrative Bias", scores.get("narrative_bias", 0.0), inverse=True)
        with score_cols[2]:
            render_score_card("Completeness", scores.get("completeness", 0.0))
        with score_cols[3]:
            render_score_card("Confidence", scores.get("confidence", 0.0))

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            render_bar_chart("Overall Score Graph", build_score_chart_data(scores))
        with chart_col2:
            render_pie_chart("Claim Stance Pie Chart", build_claim_stance_chart_data(output.get("claim_analysis", [])))

        render_calibrated_score_section(calibrated_scores)

        left_col, right_col = st.columns(2)
        with left_col:
            st.subheader("Your Article")
            st.write(article_text[:5000])
        with right_col:
            st.subheader("Sources We Compared Against")
            render_source_table(results)

        st.subheader("Source Mix")
        render_bar_chart("How many results came from each source", build_source_chart_data(results), color="#16a34a")
        st.subheader("Source Credibility")
        render_bar_chart("Average credibility score by source", build_credibility_chart_data(results), color="#0f766e")

        st.subheader("Claim Check")
        render_claim_analysis(output.get("claim_analysis", []))

        st.subheader("Where Sources Disagree")
        render_contradictions(output.get("contradictions", []))

        st.subheader("Story Framing")
        render_narrative_section(output.get("narrative_analysis", {}))

        st.subheader("Missing Sides or Viewpoints")
        render_missing_viewpoints(output.get("missing_viewpoints", {}))

        st.subheader("Loaded or Emotional Wording")
        render_biased_language(output.get("biased_language", []))
