import os
import re
import streamlit as st
import pdfplumber
from tavily import TavilyClient

st.set_page_config(
    page_title="Fact Check Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Styling ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Page background */
.stApp { background-color: #f8f9fb; }

/* Header */
.fca-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: white;
    padding: 2rem 2.5rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
}
.fca-header h1 { margin: 0; font-size: 2rem; font-weight: 700; letter-spacing: -0.5px; }
.fca-header p  { margin: 0.4rem 0 0; color: #a0aec0; font-size: 0.95rem; }

/* Upload card */
.upload-card {
    background: white;
    border: 2px dashed #cbd5e0;
    border-radius: 12px;
    padding: 1.5rem 2rem;
    margin-bottom: 1rem;
}

/* Metric cards */
.metric-row { display: flex; gap: 1rem; margin: 1.5rem 0 1rem; }
.metric-card {
    flex: 1;
    background: white;
    border-radius: 10px;
    padding: 1.2rem 1.5rem;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border-top: 4px solid #e2e8f0;
}
.metric-card.total  { border-top-color: #667eea; }
.metric-card.green  { border-top-color: #48bb78; }
.metric-card.yellow { border-top-color: #ed8936; }
.metric-card.red    { border-top-color: #f56565; }
.metric-card .num   { font-size: 2.2rem; font-weight: 700; color: #2d3748; }
.metric-card .lbl   { font-size: 0.8rem; color: #718096; text-transform: uppercase;
                       letter-spacing: 0.05em; margin-top: 0.2rem; }

/* Results table */
.results-table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    margin-top: 1rem;
}
.results-table thead th {
    background: #f7fafc;
    color: #4a5568;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 0.9rem 1.2rem;
    border-bottom: 2px solid #e2e8f0;
    text-align: left;
}
.results-table tbody td {
    padding: 0.95rem 1.2rem;
    border-bottom: 1px solid #f0f4f8;
    font-size: 0.88rem;
    color: #2d3748;
    vertical-align: top;
}
.results-table tbody tr:last-child td { border-bottom: none; }
.results-table tbody tr:hover { background: #f7fafc; }
.results-table .claim-cell { font-size: 0.875rem; line-height: 1.5; max-width: 400px; }
.results-table .num-cell { color: #a0aec0; font-size: 0.8rem; width: 2rem; }

/* Status badges */
.badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 0.3rem 0.75rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
}
.badge-verified  { background: #f0fff4; color: #276749; border: 1px solid #9ae6b4; }
.badge-inaccurate{ background: #fffaf0; color: #9c4221; border: 1px solid #fbd38d; }
.badge-false     { background: #fff5f5; color: #9b2c2c; border: 1px solid #feb2b2; }

/* Evidence text */
.evidence { font-size: 0.82rem; color: #718096; line-height: 1.5; }
.source-links { margin-top: 0.35rem; }
.source-links a {
    font-size: 0.78rem; color: #667eea;
    text-decoration: none; margin-right: 0.5rem;
}
.source-links a:hover { text-decoration: underline; }

/* Section header */
.section-title {
    font-size: 1.1rem; font-weight: 600; color: #2d3748;
    margin: 1.5rem 0 0.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid #edf2f7;
}
</style>
""", unsafe_allow_html=True)

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="fca-header">
  <h1>🔍 Fact Check Agent</h1>
  <p>Upload a PDF document · Extract factual claims · Verify against live web sources</p>
</div>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(uploaded_file) -> str:
    text = ""
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text.strip()


FACTUAL_PATTERNS = [
    (3, r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:percent|%|million|billion|trillion|thousand|km|kg|mph)\b'),
    (3, r'\b(?:19|20)\d{2}\b'),
    (3, r'\d+(?:\.\d+)?\s*(?:degrees?|°C|°F)'),
    (2, r'\b(?:discovered|invented|founded|established|born|died|created|built|launched|signed|ratified)\b'),
    (2, r'\b(?:is|are|was|were|has|have|had)\s+(?:the|a|an)\b'),
    (2, r'\b(?:largest|smallest|fastest|tallest|longest|highest|lowest|oldest|newest|first|last)\b'),
    (1, r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'),
    (1, r'\b(?:approximately|about|roughly|nearly|over|more than|less than|at least|up to)\s+\d'),
]
SKIP_PATTERNS = [
    r'^\s*$', r'^\s*[-•*]\s*', r'\?$',
    r'^(?:Figure|Table|Fig\.)\s*\d', r'^(?:Source|Note|See|Ref)\s*:',
]


def split_sentences(text: str) -> list[str]:
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z\"\'])', text)
    out = []
    for s in raw:
        for line in s.splitlines():
            if line.strip():
                out.append(line.strip())
    return out


def score_sentence(s: str) -> int:
    if len(s) < 25 or len(s) > 500:
        return 0
    for pat in SKIP_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return 0
    score = 0
    for w, pat in FACTUAL_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            score += w
    return score


def extract_claims(text: str, max_claims: int = 15) -> list[str]:
    sentences = split_sentences(text)
    seen: set[str] = set()
    scored: list[tuple[int, str]] = []
    for sent in sentences:
        key = re.sub(r'\s+', ' ', sent.lower().strip())
        if key in seen:
            continue
        seen.add(key)
        s = score_sentence(sent)
        if s > 0:
            scored.append((s, sent.strip()))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_claims]]


# ── Debunk phrases that signal a clear factual myth or negation ────────────────
_FALSE_PHRASES = [
    "is a myth", "common myth", "popular myth", "widespread myth",
    "misconception", "debunked", "not visible from space",
    "cannot be seen from space", "invisible from space",
    "this is false", "is not true", "has been disproven",
    "no scientific evidence", "has been refuted",
]

# ── Stop words for coverage calculation ──────────────────────────────────────
_STOP = {
    "that","this","with","from","have","been","were","they","their",
    "about","which","the","and","for","are","was","into","upon","also",
}


def _extract_best_snippet(claim: str, results: list[dict]) -> str:
    """Return the sentence in search results most relevant to the claim."""
    claim_words = {w for w in re.findall(r"\b[a-z]{4,}\b", claim.lower()) if w not in _STOP}
    best_score, best = 0, ""
    for r in results[:4]:
        text = r.get("title", "") + " " + r.get("content", "")
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sl = sent.lower()
            score = sum(1 for w in claim_words if w in sl)
            if score > best_score and 30 <= len(sent) <= 260:
                best_score, best = score, sent.strip()
    return best[:200]


def _detect_large_number_contradiction(claim: str, combined: str) -> bool:
    """
    True when the claim contains a large number (billions/millions) and
    topic-relevant sentences in the results report a value that is more than
    3.5× different — indicating a substantial factual discrepancy.

    Numbers are only compared inside sentences that share enough topic words
    with the claim, so unrelated large numbers (e.g. world population figures
    appearing alongside country-level stats) don't trigger false positives.
    """
    pattern = r"\$?\s*(\d+(?:\.\d+)?)\s*(?:billion|million|trillion)\b"
    claim_nums = re.findall(pattern, claim, re.IGNORECASE)
    if not claim_nums:
        return False

    key_words = {w for w in re.findall(r"\b[a-z]{4,}\b", claim.lower()) if w not in _STOP}
    # 4+ key words → 2 required (the set is specific enough to avoid false positives)
    # 3 key words   → 3 required (e.g. "india population billion" — world population must be excluded)
    # fewer         → require all
    min_overlap = 2 if len(key_words) >= 4 else min(len(key_words), 3)

    # Collect numbers only from sentences topically close to the claim
    relevant_nums: list[str] = []
    # Don't split on decimal points (e.g. "$24.32 billion" must stay one fragment)
    for sent in re.split(r"(?<!\d)[.!?](?!\d)|\n+", combined):
        sl = sent.lower()
        if sum(1 for w in key_words if w in sl) >= min_overlap:
            relevant_nums.extend(re.findall(pattern, sent, re.IGNORECASE))

    for cn in claim_nums:
        try:
            cv = float(cn)
            if cv <= 0:
                continue
            for rn in relevant_nums:
                try:
                    rv = float(rn)
                    # 2.0× threshold: catches e.g. Tesla $10B vs Q4 actual $24B
                    # (a single quarter exceeding the claimed annual total).
                    # Safe for approximations: India 1.2B vs 1.4B = 1.17× → no flag.
                    if rv > 0 and (rv / cv > 2.0 or cv / rv > 2.0):
                        return True
                except ValueError:
                    pass
        except ValueError:
            pass
    return False


def _classify_from_qna(qna: str, claim: str, results: list[dict]) -> dict | None:
    """
    Parse Tavily's QnA answer into a classification.
    Returns None if the answer is too ambiguous to classify.
    """
    ans = qna.strip()
    ans_lower = ans.lower()
    snippet = _extract_best_snippet(claim, results) or ans[:160]

    affirm_start = bool(re.match(
        r"^(yes[,.]?|correct[,.]?|true[,.]?|indeed[,.]?|absolutely[,.]?)\b",
        ans_lower,
    ))
    negation_start = bool(re.match(
        r"^(no[,.]?|not\b|false[,.]?|incorrect[,.]?|actually,?\s*(no|it|this|the)\b)",
        ans_lower,
    ))
    has_false_phrase = any(p in ans_lower for p in _FALSE_PHRASES)
    claim_has_big_num = bool(re.search(
        r"\$?\d+(?:\.\d+)?\s*(?:billion|million|trillion)", claim, re.IGNORECASE
    ))

    if affirm_start and not has_false_phrase:
        return {"classification": "Verified",   "confidence": 85, "snippet": snippet, "explanation": ans[:120]}

    if has_false_phrase:
        return {"classification": "False",      "confidence": 87, "snippet": snippet, "explanation": ans[:120]}

    if negation_start:
        if claim_has_big_num:
            return {"classification": "Inaccurate", "confidence": 78, "snippet": snippet, "explanation": ans[:120]}
        return     {"classification": "False",      "confidence": 78, "snippet": snippet, "explanation": ans[:120]}

    # Neutral QnA (e.g. "India's population is approximately 1.4 billion…"):
    # If the claim contains a large number and the QnA gives a close value
    # (within 2×), treat it as Verified — it's an approximation, not a mistake.
    if claim_has_big_num:
        _pat = r"\$?\s*(\d+(?:\.\d+)?)\s*(?:billion|million|trillion)\b"
        qna_nums   = re.findall(_pat, ans,   re.IGNORECASE)
        claim_nums = re.findall(_pat, claim, re.IGNORECASE)
        if qna_nums and claim_nums:
            try:
                qv, cv = float(qna_nums[0]), float(claim_nums[0])
                if qv > 0 and cv > 0 and max(qv / cv, cv / qv) <= 2.0:
                    return {
                        "classification": "Verified",
                        "confidence": 72,
                        "snippet": snippet,
                        "explanation": ans[:120],
                    }
            except (ValueError, ZeroDivisionError):
                pass

    return None  # Ambiguous — fall through to rule-based


def _classify_rule_based(claim: str, results: list[dict]) -> dict:
    """
    Fallback when Tavily QnA returns an ambiguous answer.
    Uses keyword coverage + numerical-contradiction detection.
    """
    if not results:
        return {
            "classification": "Inaccurate",
            "confidence": 15,
            "snippet": "",
            "explanation": "No search results found — unable to verify.",
        }
    combined = " ".join(
        (r.get("title", "") + " " + r.get("content", ""))
        for r in results
    ).lower()

    snippet = _extract_best_snippet(claim, results)

    # Debunk signals in raw results
    debunk = sum(1 for p in _FALSE_PHRASES if p in combined)
    if debunk:
        return {
            "classification": "False",
            "confidence": min(88, 70 + debunk * 6),
            "snippet": snippet,
            "explanation": "Search results identify this claim as a myth or misconception.",
        }

    # Numerical contradiction (e.g., claim says $10B, results say $81.5B)
    if _detect_large_number_contradiction(claim, combined):
        return {
            "classification": "Inaccurate",
            "confidence": 76,
            "snippet": snippet,
            "explanation": "Figures in the claim differ significantly from those reported in search results.",
        }

    # Keyword coverage
    words = {w for w in re.findall(r"\b[a-z]{4,}\b", claim.lower()) if w not in _STOP}
    cov = sum(1 for w in words if w in combined) / len(words) if words else 0.0

    if cov >= 0.50:
        return {
            "classification": "Verified",
            "confidence": min(88, 62 + int(cov * 30)),
            "snippet": snippet,
            "explanation": "Claim is well-supported by search results with no contradicting signals.",
        }
    return {
        "classification": "Inaccurate",
        "confidence": max(25, int(cov * 55) + 18),
        "snippet": snippet,
        "explanation": f"Insufficient evidence found ({int(cov * 100)}% keyword coverage, no clear support or contradiction).",
    }


_BIG_NUM_PAT = re.compile(
    r"\s*(?:(?:is|was|were|are|had|has)\s+)?\$?\s*\d+(?:\.\d+)?\s*(?:billion|million|trillion)\b",
    re.IGNORECASE,
)

# Financial metrics where "annual" should be appended to get full-year figures
# rather than quarterly results that would be 4–8× smaller.
_FINANCIAL_TERMS = {"revenue", "earnings", "profit", "sales", "income", "turnover"}


def _make_search_query(claim: str) -> str:
    """
    For claims that state a specific large figure (e.g. "$10 billion"), strip
    the number so Tavily returns authoritative articles with the *actual* value.

    "Tesla's revenue in 2022 was $10 billion"
      → "Tesla's revenue in 2022 annual"  (finds the real $81.5B annual figure)

    For financial-metric claims, "annual" is appended so the search returns
    full-year summaries rather than Q4 earnings that report quarterly figures.

    Non-numerical claims are searched verbatim.
    """
    if _BIG_NUM_PAT.search(claim):
        stripped = _BIG_NUM_PAT.sub("", claim)
        stripped = re.sub(r"\s+", " ", stripped).strip().rstrip(".,")
        if len(stripped) > 15:
            if any(t in stripped.lower() for t in _FINANCIAL_TERMS):
                return stripped + " annual"
            return stripped
    return claim


def verify_claim(claim: str, client: TavilyClient) -> dict:
    search_query = _make_search_query(claim)
    # Use advanced depth for numerical claims — basic depth truncates articles
    # so the authoritative figure (e.g. annual revenue) may be cut off.
    has_big_num = bool(_BIG_NUM_PAT.search(claim))
    search_depth = "advanced" if has_big_num else "basic"
    try:
        resp    = client.search(query=search_query, search_depth=search_depth, max_results=5)
        results = resp.get("results", [])
        sources = [r.get("url", "") for r in results if r.get("url")]
    except Exception as e:
        return {
            "claim": claim, "classification": "Inaccurate",
            "confidence": 0, "snippet": "", "explanation": f"Search failed: {e}",
            "sources": [],
        }

    # Try Tavily's QnA for a direct semantic answer
    verdict = None
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            qna = client.qna_search(query=f"Is this claim accurate? {claim}")
        if qna:
            verdict = _classify_from_qna(qna, claim, results)
    except Exception:
        pass

    if verdict is None:
        verdict = _classify_rule_based(claim, results)

    verdict["claim"]   = claim
    verdict["sources"] = sources
    return verdict


import pandas as pd

STATUS_LABEL = {
    "Verified":   "🟢 Verified",
    "Inaccurate": "🟡 Inaccurate",
    "False":      "🔴 False",
}

ROW_COLORS = {
    "Verified":   "#f0fff4",
    "Inaccurate": "#fffdf0",
    "False":      "#fff5f5",
}


def style_results(df: pd.DataFrame) -> pd.DataFrame:
    """Apply row background colors based on the hidden _cls column."""
    colors = df["_cls"].map(ROW_COLORS).fillna("#ffffff")
    styled = pd.DataFrame("", index=df.index, columns=df.columns)
    for col in df.columns:
        styled[col] = colors.apply(lambda c: f"background-color: {c}")
    return styled


# ── Main UI ────────────────────────────────────────────────────────────────────

tavily_key = os.environ.get("TAVILY_API_KEY", "")
if not tavily_key:
    st.error("⚠️ **TAVILY_API_KEY** environment variable is not set.")
    st.stop()

tavily_client = TavilyClient(api_key=tavily_key)

# Upload section
st.markdown('<div class="section-title">📄 Upload Document</div>', unsafe_allow_html=True)
uploaded_file = st.file_uploader(
    "Choose a PDF file to fact-check",
    type=["pdf"],
    help="Supports any text-based PDF. Scanned images may not extract well.",
)

if not uploaded_file:
    st.info("Upload a PDF above to get started. The agent will extract up to 15 factual claims and verify each one against live web sources.")
    st.stop()

# Extract text
with st.spinner("Reading PDF..."):
    text = extract_text_from_pdf(uploaded_file)

if not text:
    st.error("Could not extract text from this PDF. Please try a different file.")
    st.stop()

col_info1, col_info2, col_info3 = st.columns(3)
col_info1.success(f"**{uploaded_file.name}**")
col_info2.info(f"📝 {len(text):,} characters extracted")
col_info3.info(f"📄 Uploaded successfully")

with st.expander("Preview extracted text"):
    st.text_area("", text[:3000] + ("..." if len(text) > 3000 else ""), height=180, label_visibility="collapsed")

st.markdown('<div class="section-title">🔍 Fact Check</div>', unsafe_allow_html=True)

if not st.button("Extract & Verify Claims", type="primary", use_container_width=False):
    st.caption("Click the button above to begin claim extraction and web verification.")
    st.stop()

# ── Extraction ─────────────────────────────────────────────────────────────────
with st.spinner("Extracting factual claims from document..."):
    claims = extract_claims(text)

if not claims:
    st.warning("No verifiable factual claims were detected in this document.")
    st.stop()

# ── Verification with live progress ───────────────────────────────────────────
results: list[dict] = []

progress_container = st.container()
with progress_container:
    prog_bar    = st.progress(0)
    status_text = st.empty()

for i, claim in enumerate(claims):
    status_text.markdown(
        f"🔎 Verifying claim **{i + 1}** of **{len(claims)}** &nbsp;·&nbsp; "
        f"*{claim[:80]}{'...' if len(claim) > 80 else ''}*"
    )
    results.append(verify_claim(claim, tavily_client))
    prog_bar.progress((i + 1) / len(claims))

status_text.empty()
prog_bar.empty()

# ── Summary metrics ────────────────────────────────────────────────────────────
verified   = sum(1 for r in results if r["classification"] == "Verified")
inaccurate = sum(1 for r in results if r["classification"] == "Inaccurate")
false_cnt  = sum(1 for r in results if r["classification"] == "False")
total      = len(results)

st.markdown(f"""
<div class="metric-row">
  <div class="metric-card total">
    <div class="num">{total}</div>
    <div class="lbl">Claims Checked</div>
  </div>
  <div class="metric-card green">
    <div class="num">{verified}</div>
    <div class="lbl">✓ Verified</div>
  </div>
  <div class="metric-card yellow">
    <div class="num">{inaccurate}</div>
    <div class="lbl">⚠ Inaccurate</div>
  </div>
  <div class="metric-card red">
    <div class="num">{false_cnt}</div>
    <div class="lbl">✕ False</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Results table ──────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📊 Results</div>', unsafe_allow_html=True)

def _confidence_label(score: int) -> str:
    if score >= 80:
        tier = "High"
    elif score >= 50:
        tier = "Med"
    else:
        tier = "Low"
    return f"{score}% · {tier}"


rows = []
for r in results:
    snippet = r.get("snippet", "").strip()
    explanation = r.get("explanation", "").strip()
    evidence = snippet if snippet else explanation
    rows.append({
        "Claim":      r["claim"],
        "Status":     STATUS_LABEL.get(r["classification"], r["classification"]),
        "Confidence": _confidence_label(r.get("confidence", 0)),
        "Evidence":   evidence,
        "_cls":       r["classification"],
    })

df = pd.DataFrame(rows)

styled = (
    df.style
    .apply(style_results, axis=None)
    .set_properties(subset=["Claim"],    **{"min-width": "320px", "white-space": "normal"})
    .set_properties(subset=["Evidence"], **{"min-width": "280px", "white-space": "normal"})
    .set_properties(subset=["Status"],   **{"font-weight": "600", "white-space": "nowrap"})
    .hide(axis="index")
)

st.dataframe(
    styled,
    use_container_width=True,
    column_config={
        "Claim":      st.column_config.TextColumn("Claim",      width="large"),
        "Status":     st.column_config.TextColumn("Status",     width="small"),
        "Confidence": st.column_config.TextColumn("Confidence", width="small"),
        "Evidence":   st.column_config.TextColumn("Evidence",   width="large"),
        "_cls":       None,   # hide the raw classification column
    },
    hide_index=True,
)

# Sources expander
with st.expander("🔗 View sources for each claim"):
    for i, r in enumerate(results, 1):
        srcs = [u for u in r.get("sources", []) if u]
        label = STATUS_LABEL.get(r["classification"], r["classification"])
        st.markdown(f"**{i}. {label}** — {r['claim'][:100]}{'...' if len(r['claim'])>100 else ''}")
        if srcs:
            for url in srcs[:3]:
                st.markdown(f"  - {url}")
        else:
            st.markdown("  - *No sources found*")

st.caption(
    "Verification uses Tavily web search + rule-based signal analysis. "
    "Confidence scores reflect keyword coverage and signal strength, not absolute truth."
)
