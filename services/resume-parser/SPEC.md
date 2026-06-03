# Resume Parser — Technical Specification

**Job Application OS | Phase 2**
Stack: Python / FastAPI | LLM: Anthropic Claude Sonnet | Port: 8002

---

## Overview

The resume parser takes raw resume input (plain text or PDF) and produces a structured `UserProfile` JSON and a `ResumeBaseline` JSON. These are the primary inputs to the fitment engine. The parser runs as a standalone FastAPI service.

Schemas are shared with the fitment engine. See **Cross-service import strategy** below.

---

## Input Formats

### Plain text
Raw string, pasted by the user. No preprocessing required.

### PDF
Base64-encoded file upload. The service decodes and extracts text before any LLM call.

**PDF extraction:** `pdfplumber` (preferred) with `pypdf` as fallback. Extract raw text only — do not attempt to parse layout, columns, or tables. If extracted text is under 200 words, return `parse_quality: 'low'` and prompt the user to paste as plain text instead.

---

## Two-Call LLM Architecture

Do not attempt to produce both outputs in a single call. Splitting reduces hallucination and keeps each prompt focused.

Model: `claude-sonnet-4-6`, `temperature=0`

### Call 1 — Universal profile fields

**Input:** raw resume text

**Output — fields to infer from resume:**

```
target_roles               (inferred from job titles and resume summary)
total_years_experience     (calculated from work history dates)
years_in_current_discipline (PM years specifically)
current_level
highest_level_held
leveling_trajectory
primary_domain
secondary_domains
domain_years               (dict: domain → years)
worked_at_company_stages   (inferred from company context)
largest_arr_supported      (if mentioned)
largest_arr_supported_context
largest_company_size       (if mentioned)
largest_dau_supported      (if mentioned)
notable_launches           (description + impact pairs from achievements)
cross_functional_scope     (inferred from stakeholder mentions)
technical_background       (summary of pre-PM technical roles)
coding_languages           (from skills sections)
data_tools                 (from skills sections)
familiarity_with_apis      (inferred: none / low / medium / high)
current_location           (from header)
communication_artifacts    (inferred from resume content)
self_assessed_strengths    (from summary or objective section)
design_collaboration_depth (low / medium / high)
research_experience        (none / low / moderate / high)
written_communication_strength (low / medium / high)
product_areas
years_managing
largest_team_managed
stakeholder_management_level
presentation_experience
highest_degree
degree_field
university_tier
```

**Fields the parser cannot infer — must be collected via follow-up:**

```
work_arrangement           (remote / hybrid / onsite preferences)
target_industries
target_company_stages
open_to_ic_and_management  (bool)
job_search_urgency         (active / passive / open)
work_authorization         (citizen / permanent_resident / visa / needs_sponsorship)
requires_sponsorship       (bool)
willing_to_relocate        (bool)
self_assessed_gaps         (free-form weaknesses)
country
timezone
```

These fields are returned in `fields_requiring_followup` and collected via `POST /parse/followup`.

### Call 2 — Skill list

**Input:** raw resume text + the 32 canonical skill names

**Canonical skill names:**

```
platform product management    pricing and packaging
growth experimentation         0 to 1 product development
revenue metric ownership       retention metric ownership
sales-assisted GTM             enterprise product management
scaling existing products      people management
software development           data analysis
consumer product management    SMB product management
director or above leadership   product launches
legal and compliance           budget ownership
vendor management              MBA
published work                 conference speaking
notable side projects          executive exposure
product discovery              product delivery
product strategy               growth strategy
internationalization           embedded engineering partnership
technical specification writing  code reading
```

**Classification rules:**

| Classification | Meaning |
|---|---|
| `confirmed_true` | Resume contains specific evidence: achievements, tools, or role descriptions that support this skill |
| `confirmed_false` | Absence is clear AND surprising given the candidate's tenure |
| `unanswered` | Insufficient evidence to classify — do not guess |

**Bias toward `unanswered` over `confirmed_false`.** A 3-year PM without pricing experience should be `unanswered`, not `confirmed_false`, unless the resume explicitly contradicts it. Only mark `confirmed_false` when the absence is clear and meaningful.

**Output:** maps to `skills: list[Skill]` and `unanswered_skills: list[str]` on `UserProfile`.

---

## Output Schemas

Reuse `UserProfile`, `ResumeBaseline`, `Skill`, `WorkExperience`, and `NotableLaunch` from `services/fitment-engine/schemas.py`.

**Additional parse metadata** (returned alongside profile and resume):

```python
parse_quality: 'high' | 'medium' | 'low'
parse_warnings: list[str]         # e.g. 'PDF extraction produced short text (180 words)'
fields_requiring_followup: list[str]  # fields that could not be inferred
```

---

## Parse Quality Evaluation

Evaluated after both LLM calls complete.

| Level | Criteria |
|---|---|
| `high` | Work history dates present, ≥ 3 notable achievements extracted, location present, skills list non-empty |
| `medium` | Some fields missing but core competitiveness fields populated (years_experience, domain, level) |
| `low` | Extracted text under 200 words, or fewer than 2 work experiences extracted |

---

## API Endpoints

### `POST /parse`

Accepts resume input and returns parsed profile, resume, and parse metadata.

**Request body:**
```json
{
  "input_type": "text" | "pdf",
  "content": "<raw text or base64-encoded PDF>"
}
```

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

### `POST /parse/followup`

Accepts user answers to follow-up questions and updates the stored profile.

**Request body:**
```json
{
  "profile_id": "profile_abc123",
  "answers": {
    "work_arrangement": ["remote", "hybrid"],
    "target_industries": ["B2B SaaS", "Developer Tools"],
    "requires_sponsorship": false,
    "willing_to_relocate": true
  }
}
```

**Response:**
```json
{
  "profile": { ...UserProfile }
}
```

### `GET /health`

```json
{ "status": "ok" }
```

---

## Cross-Service Schema Import Strategy

`services/fitment-engine/schemas.py` is the single source of truth for `UserProfile`, `ResumeBaseline`, `Skill`, etc. Two options for sharing:

**Option A — sys.path add (used in Phase 2):**

Each service entry point adds the fitment engine directory to `sys.path` at startup:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'fitment-engine'))
from schemas import UserProfile, ResumeBaseline, Skill, WorkExperience, NotableLaunch
```

Simple, no package management, works in local dev without Docker. If the fitment engine directory moves, update the path.

**Option B — `common/` shared package:**

Extract `schemas.py` to a top-level `common/` package installed via `pip install -e common/` in each service's virtualenv. Cleanest long-term; migrate here when containerizing.

**Decision:** Option A for Phase 2. Migrate to Option B when services are containerized.

---

## Stack

| Component | Choice |
|---|---|
| Framework | FastAPI |
| PDF extraction | `pdfplumber` (preferred), `pypdf` (fallback) |
| LLM | Anthropic SDK, `claude-sonnet-4-6`, `temperature=0` |
| Storage | JSON files, `STORAGE_PATH` env var (same pattern as fitment engine) |
| Schemas | Imported from `services/fitment-engine/schemas.py` via sys.path |
| Port | 8002 |

---

## Error Handling

| Failure | Behavior |
|---|---|
| PDF extraction fails | Return 400 with message suggesting plain text |
| Extracted text < 200 words | Return 200 with `parse_quality: 'low'` and warning |
| LLM returns malformed JSON | Log raw response, return 500 |
| Missing required fields after both calls | Include in `fields_requiring_followup`; return 200 |
| `profile_id` not found on `/parse/followup` | Return 404 |

---

## Environment

```
# .env.example
ANTHROPIC_API_KEY=your_key_here
MODEL=claude-sonnet-4-6
STORAGE_PATH=data/profiles
PORT=8002
```
