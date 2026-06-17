# Fact Check Agent

A Streamlit web application that extracts factual claims from PDF documents and verifies them using Google Gemini and Tavily Search.

## Features

- **PDF Upload** — upload any PDF document for analysis
- **Text Extraction** — uses `pdfplumber` to extract readable text from PDF pages
- **Claim Extraction** — uses Gemini 2.0 Flash to identify up to 15 key factual claims
- **Web Verification** — uses Tavily Search API to find relevant web sources for each claim
- **Classification** — each claim is classified as:
  - 🟢 **Verified** — supported by search results
  - 🟡 **Inaccurate** — partially correct or misleading
  - 🔴 **False** — contradicted by search results
- **Results Table** — interactive table with status, confidence score, explanation, and source links

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd fact-check-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variables

Create a `.env` file or set these in your environment / Streamlit Cloud secrets:

```
GEMINI_API_KEY=your_google_gemini_api_key
TAVILY_API_KEY=your_tavily_api_key
```

- **GEMINI_API_KEY** — get one at https://aistudio.google.com
- **TAVILY_API_KEY** — get a free key at https://tavily.com

### 4. Run the app

```bash
streamlit run app.py
```

## Deploying to Streamlit Cloud

1. Push this repository to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your repo.
3. In **App settings → Secrets**, add:

```toml
GEMINI_API_KEY = "your_google_gemini_api_key"
TAVILY_API_KEY = "your_tavily_api_key"
```

4. Click **Deploy**.

## Stack

- [Streamlit](https://streamlit.io) — web UI framework
- [pdfplumber](https://github.com/jsvine/pdfplumber) — PDF text extraction
- [google-generativeai](https://pypi.org/project/google-generativeai/) — Gemini 2.0 Flash for claim extraction and classification
- [tavily-python](https://github.com/tavily-ai/tavily-python) — web search for claim verification
