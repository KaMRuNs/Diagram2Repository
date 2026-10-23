# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

## Project
**Diagram2Repo**: upload a photo of a hand-drawn whiteboard architecture or DB-schema diagram and get back a downloadable starter repo containing `docker-compose.yml`, `prisma/schema.prisma`, `db/init.sql`, `README.md`, `LICENSE`, `.env.example`, a `Makefile` and placeholder `services/<id>/Dockerfile`s.

Three-stage local-model pipeline (all served by Ollama):
1. **Vision summary** (`VISION_MODEL`, default `gemma3:4b`): whole-image summary, data flow and tech stack, returned as `ArchitectureSummary`.
2. **OCR + graph extraction** (`OCR_MODEL`, default `qwen2.5vl:3b`): handwriting into nodes/edges/tables, returned as `Graph`.
3. **Tool-calling agent** (`AGENT_MODEL`, default `qwen3:1.7b`): calls deterministic Python tools that write the files.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

## Layout
```
backend/   FastAPI app (Python 3.11): app/pipeline, app/tools, app/templates, app/prompts, tests/
frontend/  Vite + React + TypeScript, draw.io-style editor (React Flow + dagre)
samples/   graph fixtures (*.json) used by tests, the CLI and the UI "Samples" menu
```

## Commands
```bash
# Models: all four live in D:\ollama-models (Ollama app → Settings → Model location)
ollama list                     # expect gemma3:4b, qwen2.5vl:3b, qwen3:1.7b, qwen3:4b

# Backend (http://localhost:8000)
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
pytest
ruff check . && ruff format .

# Pipeline without the UI
python -m app.pipeline.cli ../samples/ecommerce.json --no-agent   # tools only, instant
python -m app.pipeline.cli photo.jpg                              # full pipeline (~5 min on CPU)

# Frontend (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev                     # open /?sample=ecommerce to load a sample instantly
npm run lint                    # tsc type-check
npm run build                   # dist/ is served by FastAPI at / when present
```

## Hard rules
- **Models never write files.** Only `backend/app/tools/` produce output. Tools are pure and deterministic.
- **Tools read the graph from `ToolContext`, not from tool arguments.** Small models can't reliably copy a large JSON graph into each call. The model chooses what to call and a few options (e.g. license).
- **All model I/O goes through `backend/app/llm.py`** via `make_client()`:
  - `OllamaClient` (default): Ollama's *native* `/api/chat`, not the `/v1` shim, because it gives us `keep_alive`, `format` and `think`.
  - `HostedClient` (`LLM_PROVIDER=hosted`): any OpenAI-compatible provider. The default is DigitalOcean Serverless Inference, `https://inference.do-ai.run/v1`, with a model access key in `HOSTED_API_KEY`.

  Pipeline code speaks Ollama-shaped messages only; `to_openai_messages` / `from_openai_message` translate at the edge. Run `python -m app.check_provider` after changing provider or models.
- **Hosted models must be open-weight** (event rule). On DigitalOcean: `gemma-4-31B-it` for vision/OCR and `openai-gpt-oss-20b` for the agent. Avoid "max"/commercial IDs.
- **Validate every structured model output with pydantic** (`schemas.py`), with one repair retry.
- **Model names come from config/env only.** Never hard-code them in code.
- **One model in RAM at a time** (dev box: 7 GB RAM, CPU only). Stages run sequentially under `MODEL_LOCK`, and each stage ends with `client.unload(model)`.
- **Every model call has a `num_predict` cap.** CPU generation runs at about 3–7 tokens/s, so a runaway reply costs minutes.
- **Emit YAML with `yaml.safe_dump` from a dict.** Never string-template compose files.
- **Every new tool needs** an entry in `tools/registry.py` (args model + JSON schema) and a unit test.
- **Stack choices never mutate the user's graph.** `tools/stack.apply_stack()` works on a copy, right before generation (`pipeline/run.py`). New stacks need a `TECH` entry (`catalog.py`), a starter in `starters.py`, a `StackChoice` literal, and the UI option in `StackDialog.tsx`.
- Starter code templates use `__TOKEN__` placeholders (`starters._fill`), never `str.format`, because the code is full of braces. Syntax-check generated starters when changing them (py_compile, `node --check`, esbuild for JSX).
- **The agent must always finish.** `pipeline/agent.py` runs any skipped required tool deterministically (`by: "fallback"`).
- OCR quirks are fixed in `pipeline/normalize.py` and covered by `tests/fixtures/qwen25vl_board.json` (real model output). Add new real failures there as fixtures.

## Conventions
- Python: type hints, async FastAPI, `ruff` (line length 110), `pytest` with `asyncio_mode = auto`. Prompts live in `backend/app/prompts/*.md` and are rendered with `str.replace` (they contain JSON braces).
- TypeScript: `strict`, functional components. API calls only in `src/api.ts`, and job/SSE state only in `src/useJob.ts`. Shape colors use draw.io's palette in `src/lib/graph.ts` (`KIND_STYLE`).
- Tool tests use `samples/*.json` and never call a model. Agent tests use the `FakeClient` in `tests/test_agent.py`.

## Gotchas
- **`qwen3:4b` on Ollama is the Thinking-2507 build**: thinking can't be disabled, so it reasons hundreds of tokens before each tool call (~15 min per run on CPU). `qwen3:1.7b` (hybrid) honours `think: false` and finishes in under a minute.
- **Never use `temperature: 0` with Qwen3.** Greedy decoding makes it repeat endlessly. Constrained-JSON vision calls use temperature 0; the agent uses the model's defaults.
- `llm.inline_schema()` strips JSON-schema `"title"` annotations but must keep *properties* named `title` (a past bug silently removed `ArchitectureSummary.title` from the `format` schema). `ArchitectureSummary` fields still have defaults as a safety net.
- qwen2.5vl:3b tends to:
  - tag "… API" boxes as `gateway`
  - put protocols ("rest") in `tech`
  - repeat tables as database boxes
  - attach an FK to the wrong column
  - invent a table (id/name/email/password) for a wired-up box
  - copy endpoint names onto arrows and tag every line `sql`

  `normalize.py` handles each case. Fixtures from real runs: `tests/fixtures/qwen25vl_board.json` and `qwen25vl_demo1.json` (from `samples/demo1.jpg`).
- The extract prompt must say that unboxed text is still a node and that a branching line is several edges. Without that, the model missed a node and mis-wired 3 of 6 arrows on `demo1.jpg`.
- Docker isn't installed on the dev box. Compose validity is checked in Python tests. Go isn't installed either, so `main.go` starters are only string-tested.
- `uvicorn --reload` on Windows sometimes misses changes. If the API behaves like old code, restart it.
- Keep `html-to-image` pinned at `1.11.11`: React Flow's export guide warns that newer versions break the capture.
- If `ollama list` is empty, Ollama is looking at the wrong model folder: set *Model location* to `D:\ollama-models` in the Ollama app settings (that setting overrides `OLLAMA_MODELS`).
