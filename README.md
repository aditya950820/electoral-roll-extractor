# Electoral Roll Command Center

A single-page **command center** for electoral-roll fraud-voter detection. Ingest
electoral-roll PDFs (extract per-voter records with **Mistral Document OCR**),
store them in Postgres, run fraud rules, and work a **suspects / cluster view**
that shows one voter alongside the N similar voters it matches. Built as a
**FastAPI** backend (`server.py`) serving a self-contained vanilla-JS SPA
(`web/`).

The suspects view is the centerpiece: each suspect card shows the primary voter
plus a strip of match tiles (e.g. "a voter with 4 similar voters" = 4 tiles),
with per-attribute comparison, a review queue, database explorer, ECINET
enrichment, and PDF/ZIP report exports alongside it.

## Extracted columns

`Constituency_No`, `Constituency_Name`, `Part_No`, `Serial_No` (the number in the
box), `EPIC_No`, `Name`, `Relation_Type` (Father/Husband/Mother/Other),
`Relation_Name`, `House_Number`, `Age`, `Gender`, `Page`.

## Setup

```bash
# from the project folder (a .venv already exists)
./.venv/bin/pip install -r requirements.txt

cp .env.example .env        # then paste your Mistral API key into .env
```

Get a key at https://console.mistral.ai.

Also set the login and session-cookie vars (see `.env.example`): `APP_USERNAME`,
`APP_PASSWORD_HASH` (from `python make_password.py`), and `APP_SESSION_SECRET`
(any random string).

## Run

```bash
./.venv/bin/uvicorn server:app --reload --port 8000
```

Then open http://localhost:8000 and sign in. The SPA loads the Overview
dashboard; use the left rail to reach Suspects, Review, Explore, Ingest,
Enrichment and Reports.

## Ingest options

When ingesting a PDF (Ingest view):

- **Trim cover pages** — drops the first/last pages (cover / maps / summary /
  legend); the drop counts are adjustable.
- **Structuring method**
  - **LLM** — Mistral turns the OCR text into clean rows; most robust against
    multi-column reading-order noise. Uses a few extra API calls.
  - **Regex** — free, fully local parsing. Good when OCR text is tidy.

## Swapping the OCR provider

The provider lives behind an adapter in [`ocr_providers.py`](ocr_providers.py).
To use a different one, add an `OCRProvider` subclass, register it in
`get_provider`, and set `OCR_PROVIDER=<name>` in `.env`. Nothing else changes.

## Offline test

```bash
./.venv/bin/python test_regex.py   # verifies the parser on sample roll text
```

## Files

| File | Purpose |
|------|---------|
| `server.py` | FastAPI API + serves the SPA (all endpoints under `/api`) |
| `web/` | Vanilla-JS command-center SPA (no build step) |
| `security.py` | Password hashing / verification |
| `webauth.py` | Session auth (login, logout, require_auth) |
| `reports.py` | PDF/ZIP report builders |
| `pdf_utils.py` | Trim cover/summary pages |
| `ocr_providers.py` | Swappable OCR adapter (Mistral by default) |
| `extractor.py` | OCR text → structured voter rows (LLM + regex) |
