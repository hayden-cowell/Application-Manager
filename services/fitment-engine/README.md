# Fitment Engine

Standalone Python/FastAPI microservice that evaluates a candidate's fit for a job posting using Claude. Returns a structured assessment with a score, action tier, reasoning, and tailoring suggestions.

Part of the Job Application OS. See `Input Documents/fitment-engine-spec.md` for the full technical specification.

## Setup

### 1. Prerequisites

- Python 3.12+
- An Anthropic API key

### 2. Create and activate virtual environment

```bash
cd services/fitment-engine
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Open `.env` and replace `your_key_here` with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
MODEL=claude-haiku-4-5-20251001
PROMPT_VERSION=1.0
STORAGE_PATH=data/assessments
```

## Running the server

```bash
uvicorn main:app --reload
```

The server starts at `http://localhost:8000`.

Interactive API docs are available at `http://localhost:8000/docs`.

## Running the tests

```bash
pytest tests/ -v
```

All 21 tests should pass. LLM calls are mocked — no API key required for tests.

## Running the test harness

The test harness runs all profile × job combinations and prints results.

```bash
# Server must be running first
uvicorn main:app --reload

# In a separate terminal
python test_runner.py
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/assess` | Score a job against a profile |
| `GET` | `/assessments` | List all saved assessments |
| `GET` | `/assessments/{id}` | Get a single assessment |
| `POST` | `/assessments/{id}/override` | Log a user override |
| `GET` | `/health` | Health check |

### Example: POST /assess

```json
{
  "job": {
    "job_id": "job_001",
    "title": "Senior PM",
    "company": "Acme Corp",
    "location": "Remote (US)",
    "description": "..."
  },
  "profile": { "...": "see schemas.py for full shape" },
  "resumes": [{ "...": "see schemas.py for full shape" }],
  "save_result": true
}
```

## Project structure

```
fitment-engine/
  main.py           FastAPI app and endpoints
  scorer.py         LLM call, parsing, assessment assembly
  prompts.py        System prompt (versioned) and user prompt builder
  schemas.py        All Pydantic v2 data models
  storage.py        JSON file read/write layer
  test_runner.py    Batch CLI test harness
  data/
    profiles/       User profile JSON files
    jobs/           Job posting JSON files
    resumes/        Resume baseline JSON files
    assessments/    Saved assessment outputs (created at runtime)
  tests/
    test_scorer.py  Unit tests for scoring logic
    test_api.py     Integration tests for API endpoints
```

## Sample data

Five test scenarios are included in `data/`:

| Job file | Expected result |
|----------|----------------|
| `job_strong_fit.json` | Score 85+ — strong platform PM match |
| `job_borderline.json` | Score 70–80 — apply-tier fit |
| `job_clear_skip.json` | Score <70 — VP role, underqualified |
| `job_eligibility_fail.json` | Score 0 — UK onsite, no sponsorship |
| `job_gap_match.json` | Gap called out — growth/pricing required, self-assessed gap |

## Changing the model

The model is set in `.env`. Use `claude-haiku-4-5-20251001` for development (fast, cheap). Switch to `claude-sonnet-4-6` for better reasoning quality in production.
