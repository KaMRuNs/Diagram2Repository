# Diagram2Repo

Snap a photo of a hand-drawn system architecture or database schema and get back a documented starter repository: `docker-compose.yml`, Prisma + SQL schema, README, LICENSE, `.env.example` and a Makefile.

Everything runs locally on Ollama:

| Stage | Model | Job |
|---|---|---|
| 1. Understand | `gemma3:4b` | Summarize the architecture, data flow and tech stack |
| 2. Read | `qwen2.5vl:3b` | Handwriting OCR into a node/edge/table JSON graph |
| 3. Build | `qwen3:1.7b` | Tool-calling agent that runs the file generators |

## Run it

Prerequisites: Python 3.11+, Node 20+, Ollama with the three models above.

```bash
# 1. backend
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --port 8000

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Then either:
- **Upload photo** (or drop one on the canvas). On a CPU-only laptop the three stages take about 5 minutes.
- **Samples** → *Online Bookstore* to see the editor and output instantly, without models.

Fix anything the OCR misread directly on the canvas (labels, kinds, ports, arrows, table columns), press **Regenerate**, then **Download zip**.

## Configure
Copy `.env.example` to `.env` to change models, the Ollama URL or limits. See [CLAUDE.md](CLAUDE.md) for developer notes and [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Test
```bash
cd backend && pytest        # tools, normalizer, agent loop, API; no models needed
cd frontend && npm run lint
```
