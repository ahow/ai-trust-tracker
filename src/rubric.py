"""Rubric v0-lexicon: deterministic trust-direction scorer.
PRIOR stand-in for the LLM rubric. Every score carries rubric_version so the
LLM rubric can re-score history later (30-day overlap rule applies at switch).

Scoring contract (from spec Section 3):
- Score trust specifically, not general sentiment.
- Score the author's own stance; stance_type is 'unscored' in v0 (honest gap).
- Subject-vs-mention rule: relevance encodes whether AI/company is the SUBJECT.
- Sarcasm/irony cannot be detected lexically -> flagged as a known limitation,
  partially proxied by low confidence routing to review.
"""
import re

RUBRIC_VERSION = "v0-lexicon"

AI_TERMS = [
    "artificial intelligence", "generative ai", "gen ai", "genai",
    "large language model", "llm", "llms", "foundation model", "ai model",
    "chatgpt", "openai", "claude", "anthropic", "gemini", "deepmind",
    "copilot", "grok", "deepseek", "mistral", "qwen", "llama", "midjourney",
    "stable diffusion", "ai chatbot", "chatbot", "ai agent", "agentic ai",
    "machine learning", "neural network", "ai system", "ai tool", "ai tools",
    "ai startup", "ai company", "ai companies", "ai industry", "ai safety",
    "ai regulation", "ai-generated", "ai generated", "generative models",
]
_AI_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in AI_TERMS) + r")\b", re.I)

# Trust-direction lexicon. Weight 2 = strong; 1 = moderate. Negations handled crudely.
NEG2 = ["existential risk", "catastrophic", "ai bubble burst", "unsafe ai", "ai danger",
        "cannot be trusted", "can't be trusted", "mass layoffs", "ai arms race",
        "deepfake scam", "ai disaster", "rogue ai", "ai slop", "existential threat"]
NEG1 = ["distrust", "mistrust", "don't trust", "do not trust", "skeptical", "sceptical",
        "fear", "afraid", "worried", "concern", "risk", "risky", "dangerous", "harm",
        "bias", "biased", "lawsuit", "sued", "suing", "fine", "fined", "probe",
        "investigation", "ban", "banned", "hallucinat", "deepfake", "scam", "fraud",
        "misinformation", "disinformation", "privacy violation", "data breach",
        "copyright infringement", "stolen", "theft", "plagiar", "layoff", "job losses",
        "replace workers", "replacing workers", "replace jobs", "addicted", "manipulat",
        "deceptiv", "lie", "lied", "cover-up", "whistleblower", "monopoly",
        "energy hungry", "energy consumption", "water usage", "black box", "opaque",
        "unreliable", "inaccurate", "wrong answer", "error", "fail", "flaw", "backlash",
        "outrage", "criticism", "critics", "controversy", "warning", "warns", "threat"]
POS2 = ["highly reliable", "trustworthy ai", "proven safe", "breakthrough", "game-chang",
        "revolutioniz", "highly accurate", "state-of-the-art", "best-in-class"]
POS1 = ["trust", "trusted", "reliable", "accurate", "safe", "responsible ai", "benefit",
        "helpful", "useful", "adoption", "adopt", "confidence in", "transparent",
        "open source", "open-weight", "alignment", "aligned", "guardrail", "safeguard",
        "audit", "certified", "compliance", "improve", "progress", "optimism",
        "optimistic", "excited", "promising", "impressive", "praise", "embrace",
        "positive impact", "opportunity"]

DIMENSIONS = {
    "competence":    ["hallucinat", "accurate", "inaccurate", "error", "wrong answer",
                      "unreliable", "reliable", "fail", "capability", "benchmark", "performance"],
    "integrity":     ["transparent", "opaque", "deceptiv", "lie", "cover-up", "scam",
                      "fraud", "whistleblower", "black box"],
    "safety":        ["safe", "unsafe", "dangerous", "risk", "harm", "guardrail",
                      "alignment", "existential", "rogue"],
    "accountability": ["lawsuit", "sued", "fine", "regulator", "probe", "investigation",
                      "ban", "compliance", "audit", "accountab"],
    "societal":      ["layoff", "job", "worker", "energy", "water", "climate",
                      "artist", "copyright", "creator", "deepfake", "misinformation"],
}
TOPICS = {
    "jobs":      ["layoff", "job", "worker", "employment", "replace workers", "automat"],
    "deepfakes": ["deepfake", "impersonat"],
    "safety":    ["safety", "safe", "dangerous", "harm", "existential", "guardrail", "alignment"],
    "copyright": ["copyright", "plagiar", "stolen content", "training data", "scrape"],
    "privacy":   ["privacy", "data breach", "personal data", "surveillance"],
    "energy":    ["energy", "electricity", "water", "data center", "datacenter", "carbon"],
    "bias":      ["bias", "biased", "discriminat", "fairness"],
}
_NEGATORS = ["not ", "n't ", "no ", "never ", "hardly ", "barely "]

def _count(text_lower, phrases):
    n = 0
    for p in phrases:
        n += text_lower.count(p)
    return n

def score_item(title, text):
    """Returns dict with relevance, direction, dimension, topics, confidence, review_flag."""
    title_l = (title or "").lower()
    text_l = (title or "") + " " + (text or "")
    text_l = text_l.lower()

    ai_in_title = bool(_AI_RE.search(title or ""))
    ai_in_text = bool(_AI_RE.search(text_l))

    # Subject-vs-mention rule (controversy salience-gate lesson):
    # AI in title -> subject (1.0). AI only in body + trust marker nearby -> 0.7.
    # AI only in body, no trust markers -> passing mention (0.3, dropped).
    pos_raw = _count(text_l, POS2) * 2 + _count(text_l, POS1)
    neg_raw = _count(text_l, NEG2) * 2 + _count(text_l, NEG1)

    if ai_in_title:
        relevance = 1.0
    elif ai_in_text and (pos_raw + neg_raw) > 0:
        relevance = 0.7
    elif ai_in_text:
        relevance = 0.3
    else:
        relevance = 0.0

    # Crude negation handling: "don't trust" already in NEG lexicon; flip simple "not <pos>"
    for pos in ["trust", "reliable", "safe", "accurate"]:
        for neg in _NEGATORS:
            if neg + pos in text_l:
                neg_raw += 1
                pos_raw = max(0, pos_raw - 1)

    net = pos_raw - neg_raw
    if net == 0:
        direction = 0
    else:
        direction = max(-2, min(2, net))  # integer clamp into -2..+2

    # dimension: dominant keyword family (None if none)
    dim_hits = {d: _count(text_l, ws) for d, ws in DIMENSIONS.items()}
    dimension = max(dim_hits, key=dim_hits.get) if any(dim_hits.values()) else "other"
    topics = [t for t, ws in TOPICS.items() if _count(text_l, ws) > 0] or ["other"]

    # confidence: more trust markers -> higher; single weak marker -> review
    markers = pos_raw + neg_raw
    if relevance == 0:
        confidence = 0.0
    elif markers == 0:
        confidence = 0.4   # AI item with no trust signal: direction 0, low confidence
    else:
        confidence = min(0.9, 0.55 + 0.1 * markers)
    review_flag = 1 if confidence < 0.6 else 0

    return {
        "relevance": relevance, "direction": int(direction),
        "dimension": dimension, "topics": ",".join(topics),
        "stance_type": "unscored", "confidence": round(confidence, 2),
        "review_flag": review_flag, "rubric_version": RUBRIC_VERSION,
    }

def match_companies(title, text, companies):
    """Return [(company_id, match_field)]. AI-context is guaranteed upstream
    (all items passed the AI relevance gate)."""
    out = []
    hay_title, hay_text = title or "", (title or "") + " " + (text or "")
    hay_text_l = hay_text.lower()
    for c in companies:
        hit = None
        for a in c.get("aliases_ci", []):
            if re.search(r"\b" + re.escape(a.lower()) + r"\b", hay_text_l):
                hit = "title" if a.lower() in (title or "").lower() else "text"
                break
        if not hit:
            for a in c.get("aliases_cs", []):
                if re.search(r"\b" + re.escape(a) + r"\b", hay_text):
                    hit = "title" if a in (title or "") else "text"
                    break
        if hit:
            out.append((c["id"], hit))
    return out
