# Web App — Technical Specification

**Job Application OS | Phase 2**
Backend: Python / FastAPI (port 8001) | Frontend: React / Vite (port 5173)

---

## Overview

Minimal web application connecting the resume parser, fitment engine, and (eventually) Chrome extension into a single end-to-end flow. The goal is to validate that the full pipeline works before investing in polish. Functionality over aesthetics.

The backend is an orchestration layer only — it contains no scoring or parsing logic. It delegates to the resume parser and fitment engine via HTTP and manages local profile/resume storage.

---

## Architecture

```
Browser (React / Vite :5173)
        ↓  /api/* (proxied)
Web App Backend (FastAPI :8001)
        ↓                    ↓
Resume Parser (:8002)   Fitment Engine (:8000)
```

---

## Backend (`services/web-app/backend/`)

### Service dependencies

| Service | Base URL |
|---|---|
| Fitment engine | `http://localhost:8000` |
| Resume parser | `http://localhost:8002` |

### Endpoints

#### `POST /onboard`

Accepts resume input, calls the resume parser, saves the result, and returns parse metadata.

**Request body:**
```json
{
  "input_type": "text" | "pdf",
  "content": "<raw text or base64-encoded PDF>"
}
```

**Behavior:**
1. Calls resume parser `POST /parse`
2. Saves returned `UserProfile` and `ResumeBaseline` to local storage
3. Returns the full parse response

**Response:**
```json
{
  "profile": { ...UserProfile },
  "resume": { ...ResumeBaseline },
  "parse_quality": "high" | "medium" | "low",
  "parse_warnings": ["..."],
  "fields_requiring_followup": ["work_arrangement", "target_industries", "..."]
}
```

#### `POST /onboard/followup`

Forwards follow-up answers to the resume parser and returns the updated profile.

**Pre-processing before forwarding:**
- `self_assessed_gaps`: split the free-form string on commas or newlines, strip whitespace, filter empty strings → `list[str]`
- All other fields: pass through as-is

**Request body:**
```json
{
  "profile_id": "profile_abc123",
  "answers": {
    "work_arrangement": ["remote", "hybrid"],
    "requires_sponsorship": false
  }
}
```

**Response:**
```json
{
  "profile": { ...UserProfile }
}
```

#### `POST /score`

Loads the profile and its linked resumes from local storage, calls the fitment engine, and returns the assessment.

**Request body:**
```json
{
  "job_description": "<raw JD text>",
  "profile_id": "profile_abc123",
  "title": "Senior Product Manager",   // optional — user-supplied
  "company": "Acme Corp"               // optional — user-supplied
}
```

`title` and `company` are optional. If omitted, the backend uses placeholder values (`"Unknown Role"`, `"Unknown Company"`). `location` defaults to `"Remote"`.

**Why this matters:** the fitment engine's eligibility gate uses `job.title` to detect executive roles (VP, Director) and `job.location` for onsite detection. Placeholder values are safe defaults — they won't trigger false gate failures — but supplying real values produces more accurate eligibility decisions.

**Behavior:**
1. Loads `UserProfile` from storage by `profile_id`
2. Loads all `ResumeBaseline` objects listed in `profile.resume_ids`
3. Constructs a `JobPosting` with provided `title`/`company` (or placeholders), generates a `job_id`, sets `location` to `"Remote"` unless specified
4. Calls fitment engine `POST /assess`
5. Returns the `AssessmentResponse`

**Response:** `AssessmentResponse` as defined in `services/fitment-engine/schemas.py`

#### `GET /profile/{profile_id}`

Returns the current `UserProfile` from storage.

#### `GET /health`

```json
{ "status": "ok" }
```

### Storage

JSON files, same pattern as fitment engine. `STORAGE_PATH` env var. Separate subdirectories for profiles and resumes.

### Cross-service schema import

Same sys.path strategy as the resume parser: add `../../fitment-engine` to `sys.path` at startup to import `UserProfile`, `ResumeBaseline`, `AssessmentResponse`, etc.

### Stack

| Component | Choice |
|---|---|
| Framework | FastAPI |
| HTTP client | `httpx` (same as test_runner.py) |
| Schemas | Imported from `services/fitment-engine/schemas.py` via sys.path |
| Storage | JSON files, `STORAGE_PATH` env var |
| Port | 8001 |

### Environment

```
# .env.example
FITMENT_ENGINE_URL=http://localhost:8000
RESUME_PARSER_URL=http://localhost:8002
STORAGE_PATH=data
PORT=8001
```

---

## Frontend (`services/web-app/frontend/`)

### Stack

| Component | Choice |
|---|---|
| Framework | React (Vite) |
| Styling | Plain CSS or CSS modules — no framework |
| HTTP | Fetch API — no axios |
| Routing | None — single page, conditional rendering via React state |
| API proxy | Vite `server.proxy`: `/api` → `http://localhost:8001` |

### Screen flow

```
Screen 1 (Resume Upload)
    → on success with followup needed → Screen 2 (Follow-up Questions)
    → on success with no followup needed → Screen 3 (Score a Job)

Screen 2 (Follow-up Questions)
    → on submit → Screen 3 (Score a Job)

Screen 3 (Score a Job)
    → on submit → Screen 4 (Assessment Result)

Screen 4 (Assessment Result)
    → "Score another job" → Screen 3
```

---

### Screen 1 — Resume Upload

**Purpose:** Collect the user's resume as text or PDF.

**Elements:**
- Text area: "Paste your resume here"
- File upload button: "Upload PDF" — reads file as base64, stores in state
- Submit button: "Parse Resume"
- Loading state while `POST /api/onboard` is in flight

**On success:**
- Show `parse_quality` badge (`high` / `medium` / `low`)
- If `parse_quality === 'low'`: show warning banner — "Extracted text was too short. Try pasting as plain text for better results."
- If `fields_requiring_followup.length > 0`: advance to Screen 2
- Otherwise: advance to Screen 3

**On error:** Show error message with raw detail from API response.

---

### Screen 2 — Follow-up Questions

**Purpose:** Collect fields the parser could not infer.

**Shown only if** `fields_requiring_followup` is non-empty after Screen 1.

**Important:** render inputs **only for fields present in `fields_requiring_followup`**. Do not render all 11 fields every time. Most users will have several inferred correctly (e.g. location infers timezone). The frontend maps each field name from `fields_requiring_followup` to its input component and renders only those.

**Elements:**
- One question per field from `fields_requiring_followup` — rendered dynamically
- Input types per field:

| Field | Input type |
|---|---|
| `work_arrangement` | Checkbox group: Remote / Hybrid / Onsite |
| `target_industries` | Text input (comma-separated) |
| `target_company_stages` | Checkbox group: seed / series_a / series_b / series_c / growth / public |
| `open_to_ic_and_management` | Radio: IC only / Management only / Both |
| `job_search_urgency` | Radio: Active / Passive / Open |
| `work_authorization` | Select: Citizen / Permanent Resident / Visa / Needs Sponsorship |
| `requires_sponsorship` | Radio: Yes / No |
| `willing_to_relocate` | Radio: Yes / No |
| `self_assessed_gaps` | Text area (free-form, comma- or newline-separated) |
| `country` | Text input |
| `timezone` | Text input (e.g. "PT", "ET") |

- Submit button: "Save and Continue"
- Calls `POST /api/onboard/followup` with `{ profile_id, answers }`
- On success: advance to Screen 3

---

### Screen 3 — Score a Job

**Purpose:** Accept a job description and trigger a fit assessment.

**Elements:**
- Text area: "Paste the job description here" (Chrome extension will populate this in Phase 3)
- Text input: "Job title (optional)" — maps to `title` in request body
- Text input: "Company (optional)" — maps to `company` in request body
- Submit button: "Score This Job"
- Loading state while `POST /api/score` is in flight

**On success:** advance to Screen 4 with assessment data.

**On error:** Show error message.

---

### Screen 4 — Assessment Result

**Purpose:** Display the fit assessment.

**Elements:**

| Element | Content |
|---|---|
| Score | Large numeric display (0–100) |
| Tier badge | Color-coded: `skip` (red) / `apply_as_is` (orange) / `apply` (yellow) / `light_tailoring` (green) / `strong_fit` (blue) |
| Reasoning summary | Plain text paragraph |
| Missing signals | Bulleted list — only if non-empty |
| Tailoring suggestions | Bulleted list — only if score ≥ 80 |
| Confidence | `low` / `medium` / `high` with confidence_reasons |
| "Score another job" | Button → returns to Screen 3 (preserves profile, clears JD) |

---

## Dev Setup

```bash
# 1. Start fitment engine (port 8000)
cd services/fitment-engine
uvicorn main:app --reload --port 8000

# 2. Start resume parser (port 8002)
cd services/resume-parser
uvicorn main:app --reload --port 8002

# 3. Start web app backend (port 8001)
cd services/web-app/backend
uvicorn main:app --reload --port 8001

# 4. Start frontend (port 5173)
cd services/web-app/frontend
npm run dev
```

Frontend proxies `/api/*` to `http://localhost:8001` via Vite config. No CORS configuration required in development.
