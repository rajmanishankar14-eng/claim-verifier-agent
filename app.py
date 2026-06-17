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


# Signals that indicate search results contradict the claim
DEBUNK_SIGNALS = [
    "false", "myth", "debunked", "incorrect", "wrong", "not true",
    "misconception", "disproven", "misleading", "no evidence",
    "contrary to", "disputed", "fabricated", "pseudoscience",
    "unsubstantiated", "baseless", "refuted", "rejected",
    "not supported", "no scientific basis", "contradicted",
]

# Signals that indicate search results explicitly support the claim
# Deliberately stricter than before — vague phrases like "according to"
# are removed because they don't confirm the specific claim is correct.
CONFIRM_SIGNALS = [
    "confirmed", "verified", "accurate", "is correct", "is true",
    "proven", "established fact", "well established", "scientifically proven",
    "studies confirm", "research confirms", "evidence confirms",
    "data confirms", "experts confirm", "widely accepted",
]

STOP_WORDS = {
    "the","a","an","is","are","was","were","of","in","at","by","to",
    "and","or","for","with","that","this","have","has","had","from","on",
}


def classify_from_results(claim: str, results: list[dict]) -> dict:
    """
    Classify a claim using weighted search signals.

    Decision rules (in priority order):
    1. No results → Inaccurate (unknown)
    2. Debunk > Confirm  → False
    3. Debunk > 0        → Inaccurate (contested, even if some confirmation exists)
    4. Confirm ≥ 2 AND coverage ≥ 45% → Verified
    5. Everything else   → Inaccurate (insufficient evidence)

    Coverage alone is NEVER sufficient for Verified.
    """
    if not results:
        return {
            "classification": "Inaccurate",
            "confidence": 20,
            "explanation": "No web search results found — claim could not be verified.",
        }

    combined = " ".join(
        (r.get("title", "") + " " + r.get("content", ""))
        for r in results
    ).lower()

    debunk  = sum(1 for p in DEBUNK_SIGNALS  if p in combined)
    confirm = sum(1 for p in CONFIRM_SIGNALS if p in combined)

    # Coverage: how much of the claim's vocabulary appears in results.
    # Used only to calibrate confidence, not to drive Verified on its own.
    words = {w for w in re.findall(r'\b[a-z]{4,}\b', claim.lower()) if w not in STOP_WORDS}
    cov   = sum(1 for w in words if w in combined) / len(words) if words else 0.0

    # ── Priority 1: Debunking dominates → False ───────────────────────────────
    if debunk > 0 and debunk > confirm:
        return {
            "classification": "False",
            "confidence": min(85, 50 + (debunk - confirm) * 12),
            "explanation": (
                f"Search results challenge this claim: "
                f"{debunk} contradicting signal(s) outweigh {confirm} supporting signal(s)."
            ),
        }

    # ── Priority 2: Any debunking present → Inaccurate ───────────────────────
    if debunk > 0:
        return {
            "classification": "Inaccurate",
            "confidence": min(70, 40 + debunk * 8),
            "explanation": (
                f"Results contain {debunk} contradicting signal(s) alongside "
                f"{confirm} supporting signal(s) — claim appears contested or partially wrong."
            ),
        }

    # ── Priority 3: Explicit confirmation + topic coverage → Verified ─────────
    if confirm >= 2 and cov >= 0.45:
        return {
            "classification": "Verified",
            "confidence": min(85, 50 + confirm * 7 + int(cov * 15)),
            "explanation": (
                f"{confirm} explicit confirmation signal(s) with "
                f"{int(cov * 100)}% topic coverage. No contradicting signals detected."
            ),
        }

    # ── Priority 4: Insufficient evidence → Inaccurate ───────────────────────
    if cov < 0.3:
        reason = f"topic poorly covered in results ({int(cov * 100)}% keyword match)"
    elif confirm < 2:
        reason = f"only {confirm} explicit confirmation signal(s) found (2 required)"
    else:
        reason = f"{int(cov * 100)}% coverage but confirmation signals insufficient"

    return {
        "classification": "Inaccurate",
        "confidence": max(20, 25 + int(cov * 12) + confirm * 4),
        "explanation": f"Cannot confirm — {reason}. No contradicting signals found either.",
    }


def verify_claim(claim: str, client: TavilyClient) -> dict:
    try:
        resp    = client.search(query=claim, search_depth="basic", max_results=4)
        results = resp.get("results", [])
        sources = [r.get("url", "") for r in results if r.get("url")]
    except Exception as e:
        return {
            "claim": claim, "classification": "Inaccurate",
            "confidence": 0, "explanation": f"Search failed: {e}", "sources": [],
        }
    verdict = classify_from_results(claim, results)
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

rows = []
for r in results:
    rows.append({
        "Claim":      r["claim"],
        "Status":     STATUS_LABEL.get(r["classification"], r["classification"]),
        "Confidence": f"{r.get('confidence', 0)}%",
        "Evidence":   r.get("explanation", ""),
        "_cls":       r["classification"],   # used only for styling, hidden below
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
