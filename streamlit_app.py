import os
import sys
import time
import inspect
import re
import textwrap
import copy
from datetime import datetime
from collections import Counter
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

# ensure local modules are found first
sys.path.insert(0, os.path.dirname(__file__))

from app.analysis.bias_detector import analyze_bias
from app.analysis.lexicon import CATEGORY_COLORS
from app.analysis.scorer import score_article
from app.analysis.summarizer import summarize_retrieved_chunks
from app.retrieval.index_loader import load_all_indexes
from app.retrieval.faiss_retriever import embed_query
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

    def __init__(self, started_at: float | None = None) -> None:
        self.lines: list[str] = []
        self._partial = ""
        self.started_at = started_at

    def _format_line(self, line: str) -> str:
        cleaned = line.rstrip()
        if not cleaned:
            return ""
        if self.started_at is None:
            return cleaned
        if re.match(r"^\[\s*\d+\.\d+s\]\s", cleaned):
            return cleaned
        elapsed = time.time() - self.started_at
        return f"[{elapsed:6.1f}s] {cleaned}"

    def write(self, value: str) -> int:
        if not value:
            return 0
        self._partial += value
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            formatted = self._format_line(line)
            if formatted:
                self.lines.append(formatted)
        return len(value)

    def flush(self) -> None:
        formatted = self._format_line(self._partial)
        if formatted:
            self.lines.append(formatted)
            self._partial = ""

    def get_value(self) -> str:
        self.flush()
        return "\n".join(self.lines)


def _log_with_timer(log_placeholder, log_writer: StreamlitLogWriter, started_at: float, message: str) -> None:
    """Append a timed message to stdout-backed logs and refresh the Streamlit code block."""
    print(message)
    log_placeholder.code(log_writer.get_value(), language="text")


def run_pipeline(article_text: str, log_placeholder):
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    started_at = time.time()
    log_writer = StreamlitLogWriter(started_at=started_at)
    log_placeholder.code("[   0.0s] Starting retrieval for the input article...", language="text")
    try:
        sys.stdout = log_writer
        sys.stderr = log_writer
        _log_with_timer(log_placeholder, log_writer, started_at, "Starting retrieval for the input article...")
        results = search(article_text, INDEX_BASE_DIR, top_k=6, stage_label="Main Article Retrieval")
        _log_with_timer(
            log_placeholder,
            log_writer,
            started_at,
            "Running claim verification, contradiction detection, and scoring... this process may take up to 1 to 2 minutes.",
        )
        analyze_bias_kwargs = {
            "retrieval_base_dir": INDEX_BASE_DIR,
        }
        supported_params = inspect.signature(analyze_bias).parameters
        if "initial_evidence" in supported_params:
            analyze_bias_kwargs["initial_evidence"] = results
        if "max_claims" in supported_params:
            analyze_bias_kwargs["max_claims"] = 3
        if "claim_retrieval_top_k" in supported_params:
            analyze_bias_kwargs["claim_retrieval_top_k"] = 2
        try:
            output = analyze_bias(article_text, **analyze_bias_kwargs)
        except TypeError as error:
            if "unexpected keyword argument" not in str(error):
                raise
            _log_with_timer(log_placeholder, log_writer, started_at, "Loaded analyze_bias does not support optimized kwargs; retrying with compatibility mode.")
            output = analyze_bias(article_text, retrieval_base_dir=INDEX_BASE_DIR)
        _log_with_timer(
            log_placeholder,
            log_writer,
            started_at,
            "Summarizing reranked evidence for downstream scoring... this process may take up to 1 to 2 minutes.",
        )
        summary_context = output.get("retrieved_summary_text", "")
        if not summary_context and results:
            summary_context = summarize_retrieved_chunks(results[:6], max_articles=3)
        evidence_lines = [
            f"Source: {item.get('website_name', 'Unknown')} | Title: {item.get('title', 'Untitled')} | URL: {item.get('url', '')}"
            for item in results[:8]
        ]
        evidence_text = "\n\n".join(evidence_lines)
        if summary_context:
            evidence_text = f"{summary_context}\n\nStructured Sources:\n{evidence_text}".strip()
        _log_with_timer(
            log_placeholder,
            log_writer,
            started_at,
            "Running calibrated score model... this process may take up to 1 to 2 minutes.",
        )
        calibrated_scores = score_article(article_text, evidence=evidence_text)
        _log_with_timer(log_placeholder, log_writer, started_at, "Pipeline completed.")
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
    final_logs = log_writer.get_value()
    log_placeholder.code(final_logs or "No logs captured.", language="text")
    return output, results, final_logs, calibrated_scores


def warm_retrieval_stack() -> tuple[bool, str]:
    """Warm indexes and the embedding model once per Streamlit session."""
    try:
        load_all_indexes(INDEX_BASE_DIR)
        embed_query("energy market warmup")
        return True, "Retrieval stack warmed successfully."
    except Exception as error:
        return False, f"Retrieval warmup did not fully complete: {error}"


# ---------------------------------------------------------------------------
# DEFAULT WEIGHTS (mirrors scorer.py and scoring_v2.py)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS_SCORER = {
    "credibility": {
        "factual_accuracy": 0.60,
        "evidence_support": 0.25,
        "source_reliability": 0.15,
    },
    "completeness": {
        "viewpoint_coverage": 0.60,
        "context_depth": 0.25,
        "evidence_support": 0.15,
    },
    "bias": {
        "narrative_bias": 0.70,
        "loaded_language": 0.30,
    },
    "confidence": {
        "evidence_support": 0.45,
        "source_reliability": 0.20,
        "viewpoint_coverage": 0.20,
        "json_validity": 0.15,
    },
}

DEFAULT_WEIGHTS_V2 = {
    "factual_accuracy": 0.35,
    "narrative_bias": 0.25,
    "completeness": 0.20,
    "confidence": 0.20,
}

DEFAULT_LANG_ADJUSTMENTS = {
    "narrative_bias": 0.55,
    "factual_accuracy": -0.18,
    "completeness": -0.10,
    "confidence": -0.08,
}

# ---------------------------------------------------------------------------
# PRESET WEIGHT COMBINATIONS
# ---------------------------------------------------------------------------
WEIGHT_PRESETS: dict[str, dict[str, Any]] = {
    "Balanced": {
        "description": "Original default weights — balanced across all dimensions.",
        "scorer": copy.deepcopy(DEFAULT_WEIGHTS_SCORER),
        "v2": copy.deepcopy(DEFAULT_WEIGHTS_V2),
        "lang": copy.deepcopy(DEFAULT_LANG_ADJUSTMENTS),
    },
    "Factual-First": {
        "description": "Prioritise factual accuracy and evidence support above everything else.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.75, "evidence_support": 0.20, "source_reliability": 0.05},
            "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.30, "evidence_support": 0.20},
            "bias": {"narrative_bias": 0.65, "loaded_language": 0.35},
            "confidence": {"evidence_support": 0.55, "source_reliability": 0.20, "viewpoint_coverage": 0.15, "json_validity": 0.10},
        },
        "v2": {"factual_accuracy": 0.50, "narrative_bias": 0.20, "completeness": 0.15, "confidence": 0.15},
        "lang": {"narrative_bias": 0.40, "factual_accuracy": -0.25, "completeness": -0.08, "confidence": -0.06},
    },
    "Bias-Focus": {
        "description": "Emphasise narrative bias and loaded language detection.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.50, "evidence_support": 0.30, "source_reliability": 0.20},
            "completeness": {"viewpoint_coverage": 0.65, "context_depth": 0.20, "evidence_support": 0.15},
            "bias": {"narrative_bias": 0.80, "loaded_language": 0.20},
            "confidence": {"evidence_support": 0.40, "source_reliability": 0.20, "viewpoint_coverage": 0.25, "json_validity": 0.15},
        },
        "v2": {"factual_accuracy": 0.20, "narrative_bias": 0.45, "completeness": 0.20, "confidence": 0.15},
        "lang": {"narrative_bias": 0.75, "factual_accuracy": -0.10, "completeness": -0.10, "confidence": -0.05},
    },
    "Completeness-Focus": {
        "description": "Heavily weight viewpoint coverage and context depth.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.55, "evidence_support": 0.30, "source_reliability": 0.15},
            "completeness": {"viewpoint_coverage": 0.70, "context_depth": 0.20, "evidence_support": 0.10},
            "bias": {"narrative_bias": 0.60, "loaded_language": 0.40},
            "confidence": {"evidence_support": 0.40, "source_reliability": 0.15, "viewpoint_coverage": 0.30, "json_validity": 0.15},
        },
        "v2": {"factual_accuracy": 0.25, "narrative_bias": 0.20, "completeness": 0.40, "confidence": 0.15},
        "lang": {"narrative_bias": 0.50, "factual_accuracy": -0.15, "completeness": -0.15, "confidence": -0.08},
    },
    "Quick-Check (Lenient)": {
        "description": "Lenient check — useful for rapid triage of articles.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.50, "evidence_support": 0.30, "source_reliability": 0.20},
            "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.30, "evidence_support": 0.20},
            "bias": {"narrative_bias": 0.60, "loaded_language": 0.40},
            "confidence": {"evidence_support": 0.40, "source_reliability": 0.25, "viewpoint_coverage": 0.20, "json_validity": 0.15},
        },
        "v2": {"factual_accuracy": 0.30, "narrative_bias": 0.20, "completeness": 0.25, "confidence": 0.25},
        "lang": {"narrative_bias": 0.30, "factual_accuracy": -0.10, "completeness": -0.05, "confidence": -0.05},
    },
    "Strict Evidence": {
        "description": "Strict — demands strong evidence support and source reliability.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.50, "evidence_support": 0.40, "source_reliability": 0.10},
            "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.20, "evidence_support": 0.30},
            "bias": {"narrative_bias": 0.70, "loaded_language": 0.30},
            "confidence": {"evidence_support": 0.60, "source_reliability": 0.15, "viewpoint_coverage": 0.15, "json_validity": 0.10},
        },
        "v2": {"factual_accuracy": 0.30, "narrative_bias": 0.25, "completeness": 0.25, "confidence": 0.20},
        "lang": {"narrative_bias": 0.60, "factual_accuracy": -0.20, "completeness": -0.12, "confidence": -0.10},
    },
    "Source-Quality Focus": {
        "description": "Emphasise source credibility and reliability over raw factual counts.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.40, "evidence_support": 0.25, "source_reliability": 0.35},
            "completeness": {"viewpoint_coverage": 0.55, "context_depth": 0.25, "evidence_support": 0.20},
            "bias": {"narrative_bias": 0.65, "loaded_language": 0.35},
            "confidence": {"evidence_support": 0.35, "source_reliability": 0.35, "viewpoint_coverage": 0.20, "json_validity": 0.10},
        },
        "v2": {"factual_accuracy": 0.30, "narrative_bias": 0.25, "completeness": 0.20, "confidence": 0.25},
        "lang": {"narrative_bias": 0.50, "factual_accuracy": -0.15, "completeness": -0.08, "confidence": -0.08},
    },
    "Overall-Conservative": {
        "description": "Maximum skepticism — low scores unless evidence is very strong.",
        "scorer": {
            "credibility": {"factual_accuracy": 0.65, "evidence_support": 0.30, "source_reliability": 0.05},
            "completeness": {"viewpoint_coverage": 0.65, "context_depth": 0.20, "evidence_support": 0.15},
            "bias": {"narrative_bias": 0.75, "loaded_language": 0.25},
            "confidence": {"evidence_support": 0.50, "source_reliability": 0.15, "viewpoint_coverage": 0.25, "json_validity": 0.10},
        },
        "v2": {"factual_accuracy": 0.40, "narrative_bias": 0.30, "completeness": 0.15, "confidence": 0.15},
        "lang": {"narrative_bias": 0.70, "factual_accuracy": -0.22, "completeness": -0.14, "confidence": -0.12},
    },
}


# ---------------------------------------------------------------------------
# WEIGHT RECOMPUTATION HELPER
# ---------------------------------------------------------------------------
def _clamp_w(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _weighted_sum_w(values: dict[str, float], weights: dict[str, float]) -> float:
    return round(_clamp_w(sum(values.get(k, 0.0) * w for k, w in weights.items())), 4)


def recompute_calibrated_scores(
    calibrated_scores: dict[str, Any],
    custom_scorer_weights: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Re-derive credibility / completeness / bias / confidence from stored component_scores
    using the user-supplied weight overrides, without calling the LLM again."""
    if not calibrated_scores or not calibrated_scores.get("component_scores"):
        return calibrated_scores
    cs = calibrated_scores["component_scores"]
    json_validity = float(calibrated_scores.get("normalization", {}).get("json_validity", 1.0))
    cs_with_jv = dict(cs)
    cs_with_jv["json_validity"] = _clamp_w(json_validity)
    credibility = _weighted_sum_w(cs, custom_scorer_weights["credibility"])
    completeness = _weighted_sum_w(cs, custom_scorer_weights["completeness"])
    bias = _weighted_sum_w(cs, custom_scorer_weights["bias"])
    confidence = _weighted_sum_w(cs_with_jv, custom_scorer_weights["confidence"])
    updated = dict(calibrated_scores)
    updated["credibility_score"] = credibility
    updated["completeness_score"] = completeness
    updated["bias_score"] = bias
    updated["confidence"] = confidence
    updated["_custom_weights_applied"] = True
    return updated


def recompute_v2_scores(
    output: dict[str, Any],
    custom_v2_weights: dict[str, float],
    custom_lang: dict[str, float],
) -> dict[str, float]:
    """Re-derive the v2 scores (factual_accuracy etc.) using custom weights.
    Replays the scoring_v2 formula on the already-computed sub-scores."""
    scores = dict(output.get("scores", {}))
    wl = float(output.get("weighted_language_score", 0.0))
    # Start from claim-level sub-scores before language adjustment by reversing it
    # We use the stored scores and replay language adjustment with new multipliers
    base_fa = _clamp_w(scores.get("factual_accuracy", 0.0) + (DEFAULT_LANG_ADJUSTMENTS["factual_accuracy"] * -1 * wl))
    base_nb = _clamp_w(scores.get("narrative_bias", 0.0) - (DEFAULT_LANG_ADJUSTMENTS["narrative_bias"] * wl))
    base_co = _clamp_w(scores.get("completeness", 0.0) + (DEFAULT_LANG_ADJUSTMENTS["completeness"] * -1 * wl))
    base_cf = _clamp_w(scores.get("confidence", 0.0) + (DEFAULT_LANG_ADJUSTMENTS["confidence"] * -1 * wl))
    # Reapply language adjustment with custom multipliers
    new_fa = round(_clamp_w(base_fa + custom_lang["factual_accuracy"] * wl), 4)
    new_nb = round(_clamp_w(base_nb + custom_lang["narrative_bias"] * wl), 4)
    new_co = round(_clamp_w(base_co + custom_lang["completeness"] * wl), 4)
    new_cf = round(_clamp_w(base_cf + custom_lang["confidence"] * wl), 4)
    # Recompute final score with v2 weights
    final = _clamp_w(
        new_fa * custom_v2_weights["factual_accuracy"]
        + (1.0 - new_nb) * custom_v2_weights["narrative_bias"]
        + new_co * custom_v2_weights["completeness"]
        + new_cf * custom_v2_weights["confidence"]
    )
    return {
        "factual_accuracy": new_fa,
        "narrative_bias": new_nb,
        "completeness": new_co,
        "confidence": new_cf,
        "final_score": round(final, 4),
    }


# ---------------------------------------------------------------------------
# SCORE CARD HELPERS
# ---------------------------------------------------------------------------
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


def render_count_bar_chart(title: str, items: list[dict[str, Any]], color: str = "#ef4444") -> None:
    """Render a bar chart for raw count values."""
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
                "y": {"field": "value", "type": "quantitative", "title": ""},
                "tooltip": [
                    {"field": "label", "type": "nominal"},
                    {"field": "value", "type": "quantitative"},
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
                f"<div style='padding:0.6rem 0.8rem;border-left:6px solid {color};"
                f"background:#f8fafc;color:#111827;border-radius:8px;'>"
                f"<span style='color:#111827;font-weight:700;'>Confidence:</span> "
                f"<span style='color:#111827;'>{item.get('stance_confidence', 0.0):.2f}</span><br>"
                f"<span style='color:#111827;font-weight:700;'>Support:</span> "
                f"<span style='color:#111827;'>{item.get('support_count', 0)}</span> | "
                f"<span style='color:#111827;font-weight:700;'>Contradict:</span> "
                f"<span style='color:#111827;'>{item.get('contradict_count', 0)}</span> | "
                f"<span style='color:#111827;font-weight:700;'>Neutral:</span> "
                f"<span style='color:#111827;'>{item.get('neutral_count', 0)}</span>"
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
    chart_col1, chart_col2, chart_col3 = st.columns(3)
    with chart_col1:
        render_pie_chart("Wording Category Mix", build_bias_category_chart_data(highlights))
    with chart_col2:
        render_count_bar_chart("Category Counts", build_bias_category_count_chart_data(highlights), color="#ef4444")
    with chart_col3:
        render_pie_chart("Top Matched Words", build_bias_term_chart_data(highlights))

    st.markdown("**Words Grouped By Category**")
    category_terms = build_bias_category_groups(highlights)
    for category, terms in category_terms.items():
        st.markdown(f"- **{category.replace('_', ' ').title()}**: {', '.join(terms)}")

    st.markdown("**Flagged Sentences**")
    for item in highlights:
        st.markdown(f"**Terms:** {item.get('terms', '')}")
        categories = str(item.get("categories", "")).strip()
        if categories:
            st.caption(f"Categories: {categories}")
        st.markdown(highlight_sentence_text(item), unsafe_allow_html=True)


def render_source_table(results: list[dict[str, Any]]) -> None:
    if not results:
        st.warning("No retrieval results were found for this article.")
        return
    seen_keys: set[tuple[str, str]] = set()
    for result in results:
        source_name = result.get("website_name", "Unknown")
        title = result.get("title", "Untitled")
        url = result.get("url", "")
        score = float(result.get("score", 0.0))
        dedupe_key = (str(url).strip(), str(title).strip().lower())
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        if url:
            st.markdown(f"**[{title}]({url})**")
        else:
            st.markdown(f"**{title}**")
        st.caption(f"{source_name} | Score: {score:.3f}")
        st.markdown("---")


def render_retrieved_summary(summary_text: str) -> None:
    """Render the shared retrieval summary used downstream."""
    normalized = str(summary_text or "").strip()
    if not normalized:
        st.info("No summarized evidence context was generated for this run.")
        return
    st.code(normalized, language="text")


def render_contradictions(contradictions: list[dict[str, Any]]) -> None:
    """Render contradictions as visual cards."""
    if not contradictions:
        st.info("No explicit cross-source contradictions were detected.")
        return
    for item in contradictions:
        contradiction_type = str(item.get("type", "narrative")).title()
        sources = ", ".join(item.get("sources", []))
        st.markdown(
            f"<div style='padding:0.9rem 1rem;border:1px solid #fda4af;border-radius:12px;"
            f"background:#fff1f2;margin-bottom:0.85rem;color:#111827;'>"
            f"<div style='font-weight:700;color:#7f1d1d;margin-bottom:0.45rem;'>{contradiction_type} Contradiction</div>"
            f"<div style='color:#111827;line-height:1.55;margin-bottom:0.55rem;'>{item.get('claim', '')}</div>"
            f"<div style='color:#b42318;font-weight:600;'>Sources: {sources}</div>"
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
        {"label": "Bias Score", "value": float(calibrated_scores.get("bias_score", 0.0))},
        {"label": "Confidence", "value": float(calibrated_scores.get("confidence", 0.0))},
    ]


def build_bias_category_groups(highlights: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group matched bias words by category for UI display."""
    grouped: dict[str, set[str]] = {}
    for item in highlights:
        for category, terms in dict(item.get("category_terms", {})).items():
            if not isinstance(terms, list):
                continue
            grouped.setdefault(str(category), set()).update(str(term) for term in terms if str(term).strip())
    return {
        category: sorted(terms)
        for category, terms in sorted(grouped.items())
    }


def build_bias_category_chart_data(highlights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build pie-chart data for category frequency across flagged wording."""
    counts: Counter[str] = Counter()
    for item in highlights:
        for category, terms in dict(item.get("category_terms", {})).items():
            if isinstance(terms, list):
                counts[str(category)] += len({str(term) for term in terms if str(term).strip()})

    return [
        {
            "label": category.replace("_", " ").title(),
            "value": value,
            "color": CATEGORY_COLORS.get(category, "#64748b"),
        }
        for category, value in counts.most_common()
    ]


def build_bias_term_chart_data(highlights: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """Build pie-chart data for the most frequently matched bias terms."""
    counts: Counter[str] = Counter()
    for item in highlights:
        terms = [term.strip() for term in str(item.get("terms", "")).split(",") if term.strip()]
        counts.update(terms)

    palette = ["#dc2626", "#ea580c", "#d97706", "#2563eb", "#7c3aed", "#db2777", "#059669", "#0891b2"]
    return [
        {"label": term, "value": value, "color": palette[index % len(palette)]}
        for index, (term, value) in enumerate(counts.most_common(limit))
    ]


def build_bias_category_count_chart_data(highlights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build count chart data for category frequency."""
    counts: Counter[str] = Counter()
    for item in highlights:
        for category, terms in dict(item.get("category_terms", {})).items():
            if isinstance(terms, list):
                counts[str(category)] += len({str(term) for term in terms if str(term).strip()})
    return [
        {"label": category.replace("_", " ").title(), "value": value}
        for category, value in counts.most_common()
    ]


def highlight_sentence_text(item: dict[str, Any]) -> str:
    """Highlight matched words inline using category colors."""
    text = str(item.get("text", ""))
    if not text:
        return ""

    replacements: dict[str, str] = {}
    for category, terms in dict(item.get("category_terms", {})).items():
        if not isinstance(terms, list):
            continue
        color = CATEGORY_COLORS.get(str(category), "#64748b")
        for term in terms:
            normalized_term = str(term).strip()
            if not normalized_term:
                continue
            replacements[normalized_term] = (
                f"<span style='background:{color};color:#ffffff;padding:0.08rem 0.3rem;"
                f"border-radius:0.35rem;font-weight:600;'>{normalized_term}</span>"
            )

    highlighted = text
    for term in sorted(replacements, key=len, reverse=True):
        highlighted = re.sub(
            rf"(?i)\b({re.escape(term)})\b",
            lambda match: replacements[term].replace(term, match.group(1)),
            highlighted,
        )
    return highlighted


def render_calibrated_score_section(calibrated_scores: dict[str, Any]) -> None:
    """Render additional calibrated scores from score.py."""
    if not calibrated_scores:
        return
    st.subheader("Calibrated Score View")
    if calibrated_scores.get("used_fallback", False):
        st.warning("Calibrated scoring fell back for this run, so these values may be incomplete or unavailable.")
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


def _pdf_safe_text(value: Any) -> str:
    """Normalize text so the built-in PDF font can render it safely."""
    text = str(value or "")
    return text.encode("latin-1", "replace").decode("latin-1")


def _append_report_section(lines: list[str], title: str, body_lines: list[str]) -> None:
    """Append a titled section to the report line buffer."""
    lines.append(title.upper())
    lines.extend(body_lines or ["No data available."])
    lines.append("")


def _collect_report_evidence(output: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect all evidence actually surfaced to analysis for consistent report rendering."""
    combined: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def add_item(item: dict[str, Any]) -> None:
        source = str(item.get("website_name") or item.get("source") or "Unknown").strip()
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        text = str(item.get("text", "")).strip()
        key = (source, title or url, text[:180])
        if key in seen_keys:
            return
        seen_keys.add(key)
        combined.append(
            {
                "website_name": source,
                "title": title or "Untitled",
                "url": url,
                "text": text,
                "score": float(item.get("score", 0.0)),
            }
        )

    for result in results:
        add_item(result)

    for claim_item in output.get("claim_analysis", []):
        for evidence in claim_item.get("evidence", []):
            add_item(evidence)

    return combined


def _build_report_summary_text(output: dict[str, Any], report_evidence: list[dict[str, Any]]) -> str:
    """Provide a report summary even when article-level retrieval returned nothing."""
    summary_text = str(output.get("retrieved_summary_text", "")).strip()
    if summary_text:
        return summary_text
    if not report_evidence:
        return "No summarized evidence context available."

    fallback_lines = []
    for item in report_evidence[:5]:
        excerpt = " ".join(str(item.get("text", "")).split())[:180].strip()
        line = f"- {item.get('website_name', 'Unknown')} | {item.get('title', 'Untitled')}"
        if excerpt:
            line += f": {excerpt}"
        fallback_lines.append(line)
    return "\n".join(fallback_lines) if fallback_lines else "No summarized evidence context available."


def build_report_pdf(article_text: str, output: dict[str, Any], results: list[dict[str, Any]], calibrated_scores: dict[str, Any]) -> bytes:
    """Build a downloadable PDF report from the current analysis state."""
    if fitz is None:
        raise RuntimeError("PyMuPDF is not available, so PDF export cannot be generated.")

    scores = output.get("scores", {})
    evidence_coverage = output.get("evidence_coverage", {})
    narrative = output.get("narrative_analysis", {})
    missing_viewpoints = output.get("missing_viewpoints", {})
    report_evidence = _collect_report_evidence(output, results)
    report_summary_text = _build_report_summary_text(output, report_evidence)
    total_report_evidence = max(int(evidence_coverage.get("total_evidence_items", 0)), len(report_evidence))

    report_lines: list[str] = [
        _pdf_safe_text("Evidence-Based News Bias Analyzer Report"),
        _pdf_safe_text(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"),
        "",
    ]

    _append_report_section(
        report_lines,
        "Executive Summary",
        [
            _pdf_safe_text(f"Factual Accuracy: {float(scores.get('factual_accuracy', 0.0)):.2f}"),
            _pdf_safe_text(f"Narrative Bias: {float(scores.get('narrative_bias', 0.0)):.2f}"),
            _pdf_safe_text(f"Completeness: {float(scores.get('completeness', 0.0)):.2f}"),
            _pdf_safe_text(f"Confidence: {float(scores.get('confidence', 0.0)):.2f}"),
            _pdf_safe_text(f"Evidence Items: {total_report_evidence}"),
            _pdf_safe_text(f"Consistency: {float(evidence_coverage.get('consistency', 0.0)):.2f}"),
        ],
    )

    if calibrated_scores:
        _append_report_section(
            report_lines,
            "Calibrated Scores",
            [
                _pdf_safe_text(f"Credibility: {float(calibrated_scores.get('credibility_score', 0.0)):.2f}"),
                _pdf_safe_text(f"Bias Score: {float(calibrated_scores.get('bias_score', 0.0)):.2f}"),
                _pdf_safe_text(f"Completeness: {float(calibrated_scores.get('completeness_score', 0.0)):.2f}"),
                _pdf_safe_text(f"Confidence: {float(calibrated_scores.get('confidence', 0.0)):.2f}"),
                _pdf_safe_text(f"Explanation: {calibrated_scores.get('explanation', '')}"),
            ],
        )

    _append_report_section(
        report_lines,
        "Article Excerpt",
        [_pdf_safe_text(article_text[:2500] or "No article text provided.")],
    )

    _append_report_section(
        report_lines,
        "Summarized Evidence Context",
        [_pdf_safe_text(report_summary_text)],
    )

    claim_lines: list[str] = []
    for index, item in enumerate(output.get("claim_analysis", []), start=1):
        claim_lines.append(_pdf_safe_text(f"{index}. {item.get('claim', '')}"))
        claim_lines.append(
            _pdf_safe_text(
                f"   Stance: {item.get('stance', 'NEUTRAL')} | Confidence: {float(item.get('stance_confidence', 0.0)):.2f}"
            )
        )
    _append_report_section(report_lines, "Claim Check", claim_lines)

    contradiction_lines = [
        _pdf_safe_text(
            f"- {item.get('claim', '')} | Sources: {', '.join(item.get('sources', []))}"
        )
        for item in output.get("contradictions", [])
    ]
    _append_report_section(report_lines, "Contradictions", contradiction_lines)

    narrative_lines = [
        _pdf_safe_text(f"Article Narrative: {narrative.get('article_narrative', '')}"),
        _pdf_safe_text(f"Framing Bias: {narrative.get('framing_bias', '')}"),
        _pdf_safe_text(f"Selective Emphasis: {narrative.get('selective_emphasis', '')}"),
    ]
    for item in narrative.get("source_narratives", []):
        narrative_lines.append(_pdf_safe_text(f"Source Narrative - {item.get('source', 'Unknown')}: {item.get('summary', '')}"))
    _append_report_section(report_lines, "Narrative Analysis", narrative_lines)

    missing_lines = [
        _pdf_safe_text(f"Missing Perspectives: {', '.join(missing_viewpoints.get('missing', [])) or 'None flagged'}")
    ]
    for label, value in missing_viewpoints.get("clusters", {}).items():
        missing_lines.append(_pdf_safe_text(f"{label.title()}: {value}"))
    _append_report_section(report_lines, "Viewpoint Coverage", missing_lines)

    source_lines: list[str] = []
    for result in report_evidence[:12]:
        source_lines.append(
            _pdf_safe_text(
                f"- {result.get('website_name', 'Unknown')} | {result.get('title', 'Untitled')} | Score: {float(result.get('score', 0.0)):.3f}"
            )
        )
        if result.get("url"):
            source_lines.append(_pdf_safe_text(f"  URL: {result.get('url', '')}"))
    _append_report_section(report_lines, "Compared Sources", source_lines)

    biased_lines = [
        _pdf_safe_text(
            f"- Terms: {item.get('terms', '')} | Categories: {item.get('categories', '')} | Text: {item.get('text', '')}"
        )
        for item in output.get("biased_language", [])
    ]
    _append_report_section(report_lines, "Loaded Language", biased_lines)

    doc = fitz.open()
    page_width = 595
    page_height = 842
    margin = 40
    usable_rect = fitz.Rect(margin, margin, page_width - margin, page_height - margin)

    current_page = doc.new_page(width=page_width, height=page_height)
    current_y = margin

    def add_line(text: str, font_size: float = 10, line_gap: float = 4) -> None:
        nonlocal current_page, current_y
        safe_text = _pdf_safe_text(text)
        line_height = font_size + line_gap
        if current_y + line_height > usable_rect.y1:
            current_page = doc.new_page(width=page_width, height=page_height)
            current_y = margin
        current_page.insert_text(
            fitz.Point(usable_rect.x0, current_y + font_size),
            safe_text,
            fontsize=font_size,
            fontname="helv",
            color=(0, 0, 0),
        )
        current_y += line_height

    for raw_line in report_lines:
        if not raw_line:
            current_y += 6
            continue
        font_size = 13 if raw_line.isupper() else 10
        wrap_width = 68 if font_size == 13 else 92
        normalized_line = raw_line.strip()
        wrapped_lines = textwrap.wrap(
            normalized_line,
            width=wrap_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [normalized_line]
        for line in wrapped_lines:
            add_line(line, font_size=font_size, line_gap=5 if font_size == 13 else 4)

    return doc.tobytes()


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
if "startup_warmup_done" not in st.session_state:
    with st.spinner("Preparing retrieval indexes and local models..."):
        warmed, warmup_message = warm_retrieval_stack()
    st.session_state.startup_warmup_done = True
    st.session_state.startup_warmup_ok = warmed
    st.session_state.startup_warmup_message = warmup_message

if st.session_state.get("startup_warmup_message"):
    if st.session_state.get("startup_warmup_ok"):
        st.caption(st.session_state.startup_warmup_message)
    else:
        st.warning(st.session_state.startup_warmup_message)

# ---------------------------------------------------------------------------
# SIDEBAR — SCORING WEIGHT ADJUSTER
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Scoring Weights")
    st.caption(
        "Select a scoring profile. Sliders are filled automatically. "
        "Expand Fine-tune weights below to adjust individual values."
    )

    # ── READY-MADE COMBINATIONS ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("Ready-Made Combinations")

    _PRESET_OPTIONS = {
        "Default (Balanced)": {
            "label": "Balanced",
            "description": "Equal weight across all dimensions. Suitable for general-purpose analysis.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.60, "evidence_support": 0.25, "source_reliability": 0.15},
                "completeness": {"viewpoint_coverage": 0.60, "context_depth": 0.25, "evidence_support": 0.15},
                "bias":         {"narrative_bias": 0.70, "loaded_language": 0.30},
                "confidence":   {"evidence_support": 0.45, "source_reliability": 0.20, "viewpoint_coverage": 0.20, "json_validity": 0.15},
            },
            "v2":   {"factual_accuracy": 0.35, "narrative_bias": 0.25, "completeness": 0.20, "confidence": 0.20},
            "lang": {"narrative_bias": 0.55, "factual_accuracy": -0.18, "completeness": -0.10, "confidence": -0.08},
        },
        "Factual Accuracy": {
            "label": "Factual Accuracy",
            "description": "Prioritises factual claim verification and evidence support. Recommended for hard news and investigative reporting.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.75, "evidence_support": 0.20, "source_reliability": 0.05},
                "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.30, "evidence_support": 0.20},
                "bias":         {"narrative_bias": 0.65, "loaded_language": 0.35},
                "confidence":   {"evidence_support": 0.55, "source_reliability": 0.20, "viewpoint_coverage": 0.15, "json_validity": 0.10},
            },
            "v2":   {"factual_accuracy": 0.50, "narrative_bias": 0.20, "completeness": 0.15, "confidence": 0.15},
            "lang": {"narrative_bias": 0.40, "factual_accuracy": -0.25, "completeness": -0.08, "confidence": -0.06},
        },
        "Bias Detection": {
            "label": "Bias Detection",
            "description": "Emphasises narrative framing and loaded language. Suited for opinion pieces and editorial content.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.50, "evidence_support": 0.30, "source_reliability": 0.20},
                "completeness": {"viewpoint_coverage": 0.65, "context_depth": 0.20, "evidence_support": 0.15},
                "bias":         {"narrative_bias": 0.85, "loaded_language": 0.15},
                "confidence":   {"evidence_support": 0.40, "source_reliability": 0.20, "viewpoint_coverage": 0.25, "json_validity": 0.15},
            },
            "v2":   {"factual_accuracy": 0.15, "narrative_bias": 0.50, "completeness": 0.20, "confidence": 0.15},
            "lang": {"narrative_bias": 0.80, "factual_accuracy": -0.10, "completeness": -0.10, "confidence": -0.05},
        },
        "Viewpoint Coverage": {
            "label": "Viewpoint Coverage",
            "description": "Penalises missing perspectives and one-sided coverage. Suited for political and social reporting.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.55, "evidence_support": 0.30, "source_reliability": 0.15},
                "completeness": {"viewpoint_coverage": 0.75, "context_depth": 0.15, "evidence_support": 0.10},
                "bias":         {"narrative_bias": 0.60, "loaded_language": 0.40},
                "confidence":   {"evidence_support": 0.40, "source_reliability": 0.15, "viewpoint_coverage": 0.35, "json_validity": 0.10},
            },
            "v2":   {"factual_accuracy": 0.20, "narrative_bias": 0.20, "completeness": 0.45, "confidence": 0.15},
            "lang": {"narrative_bias": 0.50, "factual_accuracy": -0.15, "completeness": -0.18, "confidence": -0.08},
        },
        "Source Reliability": {
            "label": "Source Reliability",
            "description": "Weights source credibility and diversity. Suited for cross-outlet comparative analysis.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.35, "evidence_support": 0.25, "source_reliability": 0.40},
                "completeness": {"viewpoint_coverage": 0.55, "context_depth": 0.25, "evidence_support": 0.20},
                "bias":         {"narrative_bias": 0.65, "loaded_language": 0.35},
                "confidence":   {"evidence_support": 0.30, "source_reliability": 0.45, "viewpoint_coverage": 0.15, "json_validity": 0.10},
            },
            "v2":   {"factual_accuracy": 0.25, "narrative_bias": 0.20, "completeness": 0.15, "confidence": 0.40},
            "lang": {"narrative_bias": 0.50, "factual_accuracy": -0.15, "completeness": -0.08, "confidence": -0.08},
        },
        "Strict Evidence": {
            "label": "Strict Evidence",
            "description": "Strict scoring. Requires strong, high-quality evidence at every level.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.50, "evidence_support": 0.40, "source_reliability": 0.10},
                "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.20, "evidence_support": 0.30},
                "bias":         {"narrative_bias": 0.70, "loaded_language": 0.30},
                "confidence":   {"evidence_support": 0.65, "source_reliability": 0.15, "viewpoint_coverage": 0.10, "json_validity": 0.10},
            },
            "v2":   {"factual_accuracy": 0.30, "narrative_bias": 0.25, "completeness": 0.25, "confidence": 0.20},
            "lang": {"narrative_bias": 0.60, "factual_accuracy": -0.22, "completeness": -0.14, "confidence": -0.12},
        },
        "Lenient Assessment": {
            "label": "Lenient Assessment",
            "description": "Relaxed weights for rapid triage. Reduces false positives but may miss subtle bias.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.50, "evidence_support": 0.30, "source_reliability": 0.20},
                "completeness": {"viewpoint_coverage": 0.50, "context_depth": 0.30, "evidence_support": 0.20},
                "bias":         {"narrative_bias": 0.60, "loaded_language": 0.40},
                "confidence":   {"evidence_support": 0.40, "source_reliability": 0.25, "viewpoint_coverage": 0.20, "json_validity": 0.15},
            },
            "v2":   {"factual_accuracy": 0.30, "narrative_bias": 0.20, "completeness": 0.25, "confidence": 0.25},
            "lang": {"narrative_bias": 0.30, "factual_accuracy": -0.10, "completeness": -0.05, "confidence": -0.05},
        },
        "Maximum Scrutiny": {
            "label": "Maximum Scrutiny",
            "description": "Maximum scrutiny across all dimensions. Requires robust multi-source evidence for high scores.",
            "scorer": {
                "credibility":  {"factual_accuracy": 0.65, "evidence_support": 0.30, "source_reliability": 0.05},
                "completeness": {"viewpoint_coverage": 0.65, "context_depth": 0.20, "evidence_support": 0.15},
                "bias":         {"narrative_bias": 0.80, "loaded_language": 0.20},
                "confidence":   {"evidence_support": 0.55, "source_reliability": 0.15, "viewpoint_coverage": 0.20, "json_validity": 0.10},
            },
            "v2":   {"factual_accuracy": 0.40, "narrative_bias": 0.30, "completeness": 0.15, "confidence": 0.15},
            "lang": {"narrative_bias": 0.75, "factual_accuracy": -0.25, "completeness": -0.16, "confidence": -0.14},
        },
    }

    selected_preset_key = st.selectbox(
        "Choose a scoring combination",
        list(_PRESET_OPTIONS.keys()),
        index=0,
        key="weight_preset",
    )
    _sel = _PRESET_OPTIONS[selected_preset_key]
    selected_preset_label = _sel["label"]
    st.info(f"**{_sel['label']}** — {_sel['description']}")

    def _pv(group: str, key: str) -> float:
        return float(_sel["scorer"][group].get(key, 0.0))

    def _pv2(key: str) -> float:
        return float(_sel["v2"].get(key, 0.0))

    def _plang(key: str) -> float:
        return float(_sel["lang"].get(key, 0.0))

    # ── FINE-TUNE EXPANDER ───────────────────────────────────────────────
    with st.expander("Fine-tune weights manually", expanded=False):
        st.caption("Sliders are pre-filled from the chosen combination above. Adjust to override.")

        st.markdown("**Credibility Score**")
        st.caption("→ credibility_score in calibrated view")
        cred_fa = st.slider("Factual Accuracy weight", 0.0, 1.0, _pv("credibility", "factual_accuracy"), 0.05, key="cred_fa")
        cred_es = st.slider("Evidence Support weight",  0.0, 1.0, _pv("credibility", "evidence_support"),  0.05, key="cred_es")
        cred_sr = st.slider("Source Reliability weight", 0.0, 1.0, _pv("credibility", "source_reliability"), 0.05, key="cred_sr")
        cred_total = cred_fa + cred_es + cred_sr
        st.caption(f"Sum: **{cred_total:.2f}** {'✅' if abs(cred_total - 1.0) < 0.02 else '⚠️ should ≈ 1.0'}")

        st.markdown("**Completeness Score**")
        st.caption("→ completeness_score in calibrated view")
        comp_vc = st.slider("Viewpoint Coverage weight", 0.0, 1.0, _pv("completeness", "viewpoint_coverage"), 0.05, key="comp_vc")
        comp_cd = st.slider("Context Depth weight",       0.0, 1.0, _pv("completeness", "context_depth"),       0.05, key="comp_cd")
        comp_es = st.slider("Evidence Support weight",    0.0, 1.0, _pv("completeness", "evidence_support"),    0.05, key="comp_es")
        comp_total = comp_vc + comp_cd + comp_es
        st.caption(f"Sum: **{comp_total:.2f}** {'✅' if abs(comp_total - 1.0) < 0.02 else '⚠️ should ≈ 1.0'}")

        st.markdown("**Bias Score**")
        st.caption("→ bias_score in calibrated view")
        bias_nb = st.slider("Narrative Bias weight",   0.0, 1.0, _pv("bias", "narrative_bias"),   0.05, key="bias_nb")
        bias_ll = st.slider("Loaded Language weight",  0.0, 1.0, _pv("bias", "loaded_language"),  0.05, key="bias_ll")
        bias_total = bias_nb + bias_ll
        st.caption(f"Sum: **{bias_total:.2f}** {'✅' if abs(bias_total - 1.0) < 0.02 else '⚠️ should ≈ 1.0'}")

        st.markdown("**Confidence Score**")
        st.caption("→ confidence in calibrated view")
        conf_es = st.slider("Evidence Support weight",   0.0, 1.0, _pv("confidence", "evidence_support"),   0.05, key="conf_es")
        conf_sr = st.slider("Source Reliability weight", 0.0, 1.0, _pv("confidence", "source_reliability"), 0.05, key="conf_sr")
        conf_vc = st.slider("Viewpoint Coverage weight", 0.0, 1.0, _pv("confidence", "viewpoint_coverage"), 0.05, key="conf_vc")
        conf_jv = st.slider("JSON Validity weight",      0.0, 1.0, _pv("confidence", "json_validity"),      0.05, key="conf_jv")
        conf_total = conf_es + conf_sr + conf_vc + conf_jv
        st.caption(f"Sum: **{conf_total:.2f}** {'✅' if abs(conf_total - 1.0) < 0.02 else '⚠️ should ≈ 1.0'}")

        st.markdown("**Final Score Blend (V2)**")
        st.caption("How much each dimension contributes to the blended final_score")
        v2_fa = st.slider("Factual Accuracy",         0.0, 1.0, _pv2("factual_accuracy"), 0.05, key="v2_fa")
        v2_nb = st.slider("Narrative Bias (inverted)", 0.0, 1.0, _pv2("narrative_bias"),   0.05, key="v2_nb")
        v2_co = st.slider("Completeness",             0.0, 1.0, _pv2("completeness"),     0.05, key="v2_co")
        v2_cf = st.slider("Confidence",               0.0, 1.0, _pv2("confidence"),       0.05, key="v2_cf")
        v2_total = v2_fa + v2_nb + v2_co + v2_cf
        st.caption(f"Sum: **{v2_total:.2f}** {'✅' if abs(v2_total - 1.0) < 0.02 else '⚠️ should ≈ 1.0'}")

        st.markdown("**Language Penalty Multipliers**")
        st.caption("Applied when loaded language is detected. Negative = penalty.")
        lang_nb = st.slider("Narrative Bias boost",    0.0,  1.0, _plang("narrative_bias"),   0.05, key="lang_nb")
        lang_fa = st.slider("Factual Accuracy penalty", -1.0, 0.0, _plang("factual_accuracy"), 0.01, key="lang_fa")
        lang_co = st.slider("Completeness penalty",    -1.0, 0.0, _plang("completeness"),     0.01, key="lang_co")
        lang_cf = st.slider("Confidence penalty",      -1.0, 0.0, _plang("confidence"),       0.01, key="lang_cf")

    st.markdown("---")
    if st.button("↺ Reset to Default", use_container_width=True):
        for k in list(st.session_state.keys()):
            if k.startswith(("cred_", "comp_", "bias_", "conf_", "v2_", "lang_", "weight_preset")):
                del st.session_state[k]
        st.rerun()

# Assemble final custom weight dicts from sidebar slider values
_custom_scorer_weights: dict[str, dict[str, float]] = {
    "credibility": {"factual_accuracy": cred_fa, "evidence_support": cred_es, "source_reliability": cred_sr},
    "completeness": {"viewpoint_coverage": comp_vc, "context_depth": comp_cd, "evidence_support": comp_es},
    "bias": {"narrative_bias": bias_nb, "loaded_language": bias_ll},
    "confidence": {"evidence_support": conf_es, "source_reliability": conf_sr, "viewpoint_coverage": conf_vc, "json_validity": conf_jv},
}
_custom_v2_weights: dict[str, float] = {
    "factual_accuracy": v2_fa,
    "narrative_bias": v2_nb,
    "completeness": v2_co,
    "confidence": v2_cf,
}
_custom_lang_adjustments: dict[str, float] = {
    "narrative_bias": lang_nb,
    "factual_accuracy": lang_fa,
    "completeness": lang_co,
    "confidence": lang_cf,
}

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
        report_pdf_bytes = b""

        if fitz is not None:
            try:
                report_pdf_bytes = build_report_pdf(article_text, output, results, calibrated_scores)
            except Exception as error:
                st.warning(f"PDF report export is currently unavailable: {error}")

        live_logs_container.code(logs or "No logs captured.", language="text")

        if report_pdf_bytes:
            st.download_button(
                "Download PDF Report",
                data=report_pdf_bytes,
                file_name="bias-analysis-report.pdf",
                mime="application/pdf",
                use_container_width=False,
            )

        scores = output.get("scores", {})
        st.subheader("Simple Summary")
        render_simple_summary(output)

        # ---------- SCORE OVERVIEW (custom weights applied to v2 scores) ----------
        effective_scores = recompute_v2_scores(output, _custom_v2_weights, _custom_lang_adjustments)
        st.subheader("Score Overview")
        score_cols = st.columns(4)
        with score_cols[0]:
            render_score_card("Factual Accuracy", effective_scores.get("factual_accuracy", 0.0))
        with score_cols[1]:
            render_score_card("Narrative Bias", effective_scores.get("narrative_bias", 0.0))
        with score_cols[2]:
            render_score_card("Completeness", effective_scores.get("completeness", 0.0))
        with score_cols[3]:
            render_score_card("Confidence", effective_scores.get("confidence", 0.0))

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            render_bar_chart("Overall Score Graph", build_score_chart_data(effective_scores))
        with chart_col2:
            render_pie_chart("Claim Stance Pie Chart", build_claim_stance_chart_data(output.get("claim_analysis", [])))

        # Apply custom weights to calibrated scores (no re-inference needed)
        effective_calibrated = recompute_calibrated_scores(calibrated_scores, _custom_scorer_weights)
        effective_scores = recompute_v2_scores(output, _custom_v2_weights, _custom_lang_adjustments)

        # Show indicator when custom weights differ from defaults
        _using_custom = (selected_preset_label != "Default (Balanced)")
        if _using_custom:
            st.info(f"⚖️ Scores recalculated using **{selected_preset}** weight preset. Adjust sliders in the sidebar or run again to refresh.")

        render_calibrated_score_section(effective_calibrated)

        left_col, right_col = st.columns(2)
        with left_col:
            st.subheader("Your Article")
            st.write(article_text[:5000])
        with right_col:
            st.subheader("Sources We Compared Against")
            render_source_table(results)

        st.subheader("Summarized Evidence Context")
        render_retrieved_summary(output.get("retrieved_summary_text", ""))

        st.subheader("Source Mix")
        render_count_bar_chart("How many results came from each source", build_source_chart_data(results), color="#16a34a")
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
