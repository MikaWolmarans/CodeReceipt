# CodeReceipt

CodeReceipt converts a repository into a plain-English "owner's manual" PDF.

## Backend stack
- FastAPI + Uvicorn
- MongoDB Atlas (session + rate-limit counters)
- OpenRouter (`google/gemma-3-27b-it:free`) for two-pass analysis
- WeasyPrint + Jinja2 for in-memory PDF export

## API
- `POST /analyse` (`multipart/form-data`): provide either `url` or `zip_file`, optional `options_json` and `session_id`
- `GET /status/{session_id}`
- `GET /export/{session_id}`
- `GET /health`

## Local run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Security notes
- Strict host allowlist for repo URLs: GitHub, GitLab, Bitbucket
- ZIP limit, ZIP-bomb checks, and file-count cap
- `.env` files and binaries are excluded before LLM processing
- CORS restricted to `FRONTEND_URL`
- PDF generation blocks external resource fetching
