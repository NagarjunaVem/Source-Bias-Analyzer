"""Shared categorized lexicon for framing and loaded-language detection."""

from __future__ import annotations

CATEGORIZED_BIAS_LEXICON: dict[str, set[str]] = {
    "alarmist": {
        "catastrophic",
        "chaotic",
        "crisis",
        "disaster",
        "dramatic",
        "extreme",
        "furious",
        "grim",
        "massive",
        "outrageous",
        "severe",
        "shocking",
        "sobering",
        "terrifying",
        "devastating",
        "grave",
        "dramatically",
    },
    "certainty_overclaim": {
        "clearly",
        "definitely",
        "obviously",
        "undeniably",
        "certainly",
        "prove",
        "proves",
        "proven",
        "always",
        "never",
    },
    "conflict_escalation": {
        "blasted",
        "collapse",
        "domino",
        "hostage",
        "radical",
        "slam",
        "stalemate",
        "warpath",
        "escalation",
        "escalate",
        "escalating",
        "showdown",
        "retaliation",
        "retaliate",
        "retaliatory",
        "attack",
        "attacks",
    },
    "moral_judgment": {
        "disgraceful",
        "disastrous",
        "delusional",
        "reckless",
        "shameful",
        "corrupt",
        "failure",
        "failed",
        "cowardly",
        "dangerous",
    },
    "propaganda_framing": {
        "admits",
        "admitted",
        "exposed",
        "so-called",
        "propaganda",
        "regime",
        "mouthpiece",
        "cover-up",
        "coverup",
    },
    "derision_ridicule": {
        "mocked",
        "laughable",
        "absurd",
        "ridiculous",
        "pathetic",
        "scoffed",
        "sneered",
        "derided",
    },
}

CATEGORY_WEIGHTS: dict[str, float] = {
    "alarmist": 1.0,
    "certainty_overclaim": 1.15,
    "conflict_escalation": 1.2,
    "moral_judgment": 1.35,
    "propaganda_framing": 1.5,
    "derision_ridicule": 1.25,
}

CATEGORY_COLORS: dict[str, str] = {
    "alarmist": "#f97316",
    "certainty_overclaim": "#eab308",
    "conflict_escalation": "#ef4444",
    "moral_judgment": "#dc2626",
    "propaganda_framing": "#8b5cf6",
    "derision_ridicule": "#ec4899",
}

BIAS_LEXICON: set[str] = {
    term
    for terms in CATEGORIZED_BIAS_LEXICON.values()
    for term in terms
}

TERM_TO_CATEGORY: dict[str, str] = {
    term: category
    for category, terms in CATEGORIZED_BIAS_LEXICON.items()
    for term in terms
}
