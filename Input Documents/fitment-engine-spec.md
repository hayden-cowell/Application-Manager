# Fitment Engine — Technical Specification

**Job Application OS | v1.0**
Stack: Python / FastAPI | LLM: Anthropic Claude | Storage: JSON file (prototype)

> Pass this document to Claude Code with the instruction: "Build this exactly as specified. Ask me before making any architectural decisions not covered here."

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Data Schemas](#3-data-schemas)
4. [Scoring Logic](#4-scoring-logic)
5. [API Endpoints](#5-api-endpoints)
6. [Storage Layer](#6-storage-layer)
7. [Test Harness](#7-test-harness)
8. [Error Handling](#8-error-handling)
9. [Running the Prototype](#9-running-the-prototype)
10. [Instructions for Claude Code](#10-instructions-for-claude-code)

---

## 1. Overview

This spec covers the fitment engine in isolation. The goal is a working prototype that takes a job description and a user profile and returns a structured fit assessment. Everything else in the product (Chrome extension, tracker, session system) depends on this working well, so it gets built first.

The prototype is a standalone Python service with a REST API, a JSON file for storage, and a test harness that lets you run assessments against a set of sample jobs and profiles. No frontend required at this stage.

---

## 2. Architecture

### Project structure

```
fitment-engine/
  main.py                  # FastAPI app entry point
  scorer.py                # Core scoring logic and LLM calls
  prompts.py               # All prompt templates (versioned)
  schemas.py               # Pydantic models for all data structures
  storage.py               # JSON file read/write layer
  test_runner.py           # CLI to run batch assessments
  data/
    profiles/              # Sample user profiles (.json)
    jobs/                  # Sample job postings (.json)
    resumes/               # Sample resume baselines (.json)
    assessments/           # Saved assessment outputs (.json)
  tests/
    test_scorer.py         # Unit tests for scoring logic
    test_api.py            # Integration tests for API endpoints
  requirements.txt
  .env.example             # ANTHROPIC_API_KEY placeholder
  README.md                # Setup and usage instructions
```

### Dependencies

```
# requirements.txt
fastapi>=0.111.0
uvicorn>=0.29.0
anthropic>=0.25.0
pydantic>=2.7.0
python-dotenv>=1.0.0
pytest>=8.0.0
httpx>=0.27.0          # for test client
```

### Environment

```
# .env.example
ANTHROPIC_API_KEY=your_key_here
MODEL=claude-haiku-4-5-20251001   # use Haiku for prototype (cost)
PROMPT_VERSION=1.0
STORAGE_PATH=data/assessments
```

> **Note:** Use Haiku for the prototype. It's fast and cheap enough that you can run dozens of test assessments without worrying about cost. Swap to Sonnet when you need better reasoning quality.

---

## 3. Data Schemas

All schemas are defined in `schemas.py` using Pydantic v2. These are the source of truth for data shape across the whole service.

### UserProfile

The full profile schema, flattened into a single Pydantic model. Stored as JSON and passed directly to the scoring prompt.

```python
# schemas.py
from pydantic import BaseModel, Field
from typing import Optional

class NotableLaunch(BaseModel):
    description: str
    impact: str

class UserProfile(BaseModel):
    # Identity and targeting
    target_roles: list[str]
    target_industries: list[str]
    excluded_industries: list[str] = []
    work_arrangement: list[str]           # ['remote', 'hybrid', 'onsite']
    target_company_stages: list[str]
    open_to_ic_and_management: bool
    job_search_urgency: str               # 'active', 'passive', 'open'

    # Experience and seniority
    total_years_experience: int
    years_in_current_discipline: int
    current_level: str
    highest_level_held: str
    leveling_trajectory: str
    has_management_experience: bool
    years_managing: Optional[int] = None
    largest_team_managed: Optional[int] = None
    has_director_or_above_experience: bool

    # Domain and industry depth
    primary_domain: str
    secondary_domains: list[str] = []
    domain_years: dict[str, int]
    worked_at_company_stages: list[str]
    has_enterprise_experience: bool
    has_smb_experience: bool
    has_consumer_experience: bool
    has_0_to_1_experience: bool
    has_scaling_experience: bool
    has_platform_product_experience: bool
    has_growth_experience: bool

    # Technical depth
    can_read_code: bool
    can_write_code: bool
    coding_languages: list[str] = []
    technical_background: Optional[str] = None
    comfortable_with_data: bool
    data_tools: list[str] = []
    has_worked_embedded_with_engineering: bool
    has_written_technical_specs: bool
    familiarity_with_apis: str             # 'none', 'low', 'medium', 'high'

    # Product craft
    product_areas: list[str] = []
    strong_in_discovery: bool
    strong_in_delivery: bool
    strong_in_strategy: bool
    strong_in_growth: bool
    has_pricing_experience: bool
    has_internationalization_experience: bool
    has_launched_products: bool
    notable_launches: list[NotableLaunch] = []
    design_collaboration_depth: str        # 'low', 'medium', 'high'
    research_experience: str               # 'none', 'low', 'moderate', 'high'

    # Scope and impact
    largest_company_size: Optional[int] = None
    smallest_company_size: Optional[int] = None
    largest_arr_supported: Optional[str] = None
    largest_dau_supported: Optional[int] = None
    has_owned_revenue_metric: bool
    has_owned_retention_metric: bool
    cross_functional_scope: list[str] = []
    has_worked_with_sales: bool
    has_worked_with_legal_compliance: bool
    budget_ownership: bool
    vendor_management: bool

    # Credentials and education
    highest_degree: Optional[str] = None
    degree_field: Optional[str] = None
    university_tier: Optional[str] = None
    has_mba: bool = False
    certifications: list[str] = []
    has_published_work: bool = False
    has_conference_speaking: bool = False
    has_notable_side_projects: bool = False

    # Work authorization
    country: str
    work_authorization: str               # 'citizen', 'permanent_resident', 'visa', 'needs_sponsorship'
    requires_sponsorship: bool
    willing_to_relocate: bool
    current_location: str
    timezone: str

    # Soft signals
    communication_artifacts: list[str] = []
    stakeholder_management_level: Optional[str] = None
    has_exec_exposure: bool
    presentation_experience: Optional[str] = None
    written_communication_strength: str   # 'low', 'medium', 'high'
    self_assessed_strengths: list[str] = []
    self_assessed_gaps: list[str] = []

    # Metadata
    profile_id: str
    profile_version: int = 1
    onboarding_complete: bool = False
```

### JobPosting

```python
class JobPosting(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str                      # full text, no truncation
    source_url: Optional[str] = None
    import_source: Optional[str] = None   # 'linkedin', 'indeed', 'ziprecruiter', 'manual'
    imported_at: Optional[str] = None     # ISO timestamp
```

### ResumeBaseline

```python
class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: str                       # 'YYYY-MM'
    end_date: Optional[str] = None        # None = current role
    company_size: Optional[int] = None
    company_stage: Optional[str] = None
    description: str                      # role summary
    key_achievements: list[str]           # bullet points with metrics where possible
    skills_used: list[str]

class ResumeBaseline(BaseModel):
    resume_id: str
    name: str                             # e.g. 'Platform PM', 'Consumer Apps PM'
    role_type: str                        # used for matching
    work_experience: list[WorkExperience]
    skills: list[str]
    version: int = 1
    last_used: Optional[str] = None
```

### FitAssessment (output)

This is what the scoring engine returns. The structure is fixed -- the LLM is forced to produce JSON matching this schema exactly. Every field is required.

```python
class EligibilityGate(BaseModel):
    passed: bool
    reasons: list[str]                    # specific reasons if failed

class ScoringComponent(BaseModel):
    score: int                            # 0-100 for this component
    signals: list[str]                    # what drove the score (must cite JD phrases)
    gaps: list[str]                       # specific missing signals

class FitAssessment(BaseModel):
    assessment_id: str
    job_id: str
    profile_id: str
    prompt_version: str
    created_at: str                       # ISO timestamp

    # Gate
    eligibility: EligibilityGate

    # Component scores (only populated if eligibility passed)
    competitiveness: Optional[ScoringComponent] = None
    evidence_strength: Optional[ScoringComponent] = None

    # Final output
    score: int                            # 0-100 composite
    action_tier: str                      # 'skip', 'apply', 'light_tailoring', 'strong_fit'
    recommended_resume_id: Optional[str] = None

    # Explanation
    reasoning_summary: str                # 2-4 sentence plain English explanation
    missing_signals: list[str]            # things that would improve the score
    tailoring_suggestions: list[str]      # only populated if score >= 80

    # Confidence
    confidence_level: str                 # 'low', 'medium', 'high'
    confidence_reasons: list[str]         # what drove the confidence level

    # Override tracking
    user_overridden: bool = False
    override_action: Optional[str] = None
```

### ScoreRequest (API input)

```python
class ScoreRequest(BaseModel):
    job: JobPosting
    profile: UserProfile
    resumes: list[ResumeBaseline]
    save_result: bool = True
```

---

## 4. Scoring Logic

All scoring logic lives in `scorer.py`. The LLM does the reasoning but the structure it returns is fixed. `scorer.py` assembles the prompt, calls the API, parses the response, and falls back gracefully on failure.

### scorer.py

```python
# scorer.py
import anthropic
import json
import os
from datetime import datetime, timezone
from uuid import uuid4
from schemas import ScoreRequest, FitAssessment
from prompts import build_scoring_prompt, PROMPT_VERSION

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL  = os.getenv('MODEL', 'claude-haiku-4-5-20251001')

def score_job(request: ScoreRequest) -> FitAssessment:
    prompt = build_scoring_prompt(request)
    raw    = call_llm(prompt)
    parsed = parse_response(raw)
    result = build_assessment(parsed, request)
    return result

def call_llm(prompt: dict) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0,          # non-negotiable -- do not change
        system=prompt['system'],
        messages=[{'role': 'user', 'content': prompt['user']}]
    )
    return response.content[0].text

def parse_response(raw: str) -> dict:
    # Strip markdown fences if the model adds them despite instructions
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1].rsplit('```', 1)[0]
    return json.loads(cleaned)

def build_assessment(parsed: dict, request: ScoreRequest) -> FitAssessment:
    return FitAssessment(
        assessment_id=str(uuid4()),
        job_id=request.job.job_id,
        profile_id=request.profile.profile_id,
        prompt_version=PROMPT_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        **parsed
    )
```

### prompts.py

#### System prompt

This is the scorecard the model fills out. **Do not paraphrase or restructure this prompt.**

```python
# prompts.py
PROMPT_VERSION = '1.0'

SYSTEM_PROMPT = """
You are a fit scoring engine for a job application tool. Your job is to evaluate
how likely a candidate is to get an interview for a specific role.

You must follow this exact evaluation process in order:

STEP 1 -- ELIGIBILITY GATE
Check hard requirements only:
- Does the candidate meet the minimum years of experience stated in the JD?
- Is the role type aligned with what they are targeting?
- Is the location/work arrangement compatible?
- Do they have the required work authorization?

If any hard requirement fails, set eligibility.passed = false and stop.
Set score = 0 and action_tier = 'skip'.
Do not evaluate competitiveness or evidence strength.

STEP 2 -- COMPETITIVENESS (only if eligibility passed)
Evaluate how competitive the candidate is relative to the likely applicant pool.
Consider:
- Years of relevant experience vs. what the role actually requires (not just the minimum)
- Domain and industry relevance
- Scope of previous work (company size, ARR, DAU, team size)
- Demonstrated impact (cite specific phrases from the JD when flagging gaps)
Score 0-100. Most candidates who pass eligibility will score 50-80 here.

STEP 3 -- EVIDENCE STRENGTH (only if eligibility passed)
Evaluate how clearly the resume supports the required skills.
Consider:
- Are the required skills explicitly present in the resume?
- Are achievements measurable and specific?
- Does the resume tell a coherent story for this type of role?
Score 0-100.

STEP 4 -- COMPOSITE SCORE
Calculate the final score:
- If eligibility failed: score = 0
- Otherwise: score = round(competitiveness.score * 0.6 + evidence_strength.score * 0.4)

STEP 5 -- ACTION TIER
- score < 70:   action_tier = 'skip'
- score 70-79:  action_tier = 'apply'
- score 80-89:  action_tier = 'light_tailoring'
- score 90-100: action_tier = 'strong_fit'

STEP 6 -- CONFIDENCE
Set confidence_level based on:
- 'low': profile has significant missing fields, or JD is vague/sparse
- 'medium': profile is reasonably complete, JD has some ambiguity
- 'high': profile is complete, JD is detailed, match or mismatch is clear
Always explain what drove the confidence level in confidence_reasons.

CRITICAL RULES:
- Do not be optimistic. Score for interview likelihood, not for encouragement.
- Always cite specific phrases from the job description when identifying gaps.
- If the candidate has a self-assessed gap that the JD requires, call it out explicitly.
- tailoring_suggestions should only be populated if score >= 80. Return empty list otherwise.
- Your entire response must be valid JSON. No text outside the JSON object. No markdown fences.

REQUIRED OUTPUT SCHEMA:
{
  "eligibility": {
    "passed": true or false,
    "reasons": ["reason 1", "reason 2"]
  },
  "competitiveness": {
    "score": 0-100,
    "signals": ["signal 1"],
    "gaps": ["gap 1"]
  },
  "evidence_strength": {
    "score": 0-100,
    "signals": ["signal 1"],
    "gaps": ["gap 1"]
  },
  "score": 0-100,
  "action_tier": "skip | apply | light_tailoring | strong_fit",
  "recommended_resume_id": "resume_id or null",
  "reasoning_summary": "2-4 sentence plain English explanation",
  "missing_signals": ["thing 1", "thing 2"],
  "tailoring_suggestions": ["suggestion 1"],
  "confidence_level": "low | medium | high",
  "confidence_reasons": ["reason 1"]
}
"""
```

#### User prompt builder

```python
def build_scoring_prompt(request: ScoreRequest) -> dict:
    profile_json = request.profile.model_dump_json(indent=2)
    resumes_json = json.dumps(
        [r.model_dump() for r in request.resumes], indent=2
    )

    user_content = f"""
JOB POSTING
===========
Title: {request.job.title}
Company: {request.job.company}
Location: {request.job.location}

Description:
{request.job.description}

CANDIDATE PROFILE
=================
{profile_json}

RESUME BASELINES
================
{resumes_json}

Evaluate this candidate for this role and return the JSON assessment.
"""

    return {
        'system': SYSTEM_PROMPT,
        'user': user_content
    }
```

### Resume selection logic

The engine picks the best baseline before calling the LLM. This is deterministic, not LLM-driven.

```python
def select_best_resume(
    job: JobPosting,
    resumes: list[ResumeBaseline]
) -> Optional[ResumeBaseline]:
    if not resumes:
        return None

    # Exact role type match first
    job_title_lower = job.title.lower()
    for resume in resumes:
        if resume.role_type.lower() in job_title_lower:
            return resume

    # Fall back to most recently used
    with_dates = [r for r in resumes if r.last_used]
    if with_dates:
        return sorted(with_dates, key=lambda r: r.last_used, reverse=True)[0]

    # Otherwise return first
    return resumes[0]
```

---

## 5. API Endpoints

Built with FastAPI. All endpoints return JSON. No auth, no pagination, no rate limiting for the prototype.

### POST /assess

The core endpoint. Takes a job, profile, and resumes. Returns a full fit assessment.

```python
# main.py
from fastapi import FastAPI, HTTPException
from schemas import ScoreRequest, FitAssessment, OverrideRequest
from scorer import score_job
from storage import save_assessment, get_assessment, list_assessments
from prompts import PROMPT_VERSION

app = FastAPI(title='Fitment Engine', version='1.0')

@app.post('/assess', response_model=FitAssessment)
async def assess(request: ScoreRequest):
    try:
        result = score_job(request)
        if request.save_result:
            save_assessment(result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### GET /assessments

Returns all saved assessments.

```python
@app.get('/assessments', response_model=list[FitAssessment])
async def get_assessments():
    return list_assessments()
```

### GET /assessments/{assessment_id}

```python
@app.get('/assessments/{assessment_id}', response_model=FitAssessment)
async def get_single(assessment_id: str):
    result = get_assessment(assessment_id)
    if not result:
        raise HTTPException(status_code=404, detail='Assessment not found')
    return result
```

### POST /assessments/{assessment_id}/override

Logs when a user disagrees with a recommendation. Primary signal for scoring quality.

```python
class OverrideRequest(BaseModel):
    action: str     # 'applied_anyway', 'skipped_anyway'
    note: Optional[str] = None

@app.post('/assessments/{assessment_id}/override')
async def override(assessment_id: str, body: OverrideRequest):
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail='Not found')
    assessment.user_overridden = True
    assessment.override_action = body.action
    save_assessment(assessment)
    return {'status': 'logged'}
```

### GET /health

```python
@app.get('/health')
async def health():
    return {'status': 'ok', 'prompt_version': PROMPT_VERSION}
```

---

## 6. Storage Layer

Everything is stored as JSON files. The storage layer is intentionally thin so it's easy to swap for a database later. Nothing outside `storage.py` touches the filesystem directly.

```python
# storage.py
import json
import os
from pathlib import Path
from typing import Optional
from schemas import FitAssessment

STORAGE_PATH = Path(os.getenv('STORAGE_PATH', 'data/assessments'))
STORAGE_PATH.mkdir(parents=True, exist_ok=True)

def save_assessment(a: FitAssessment) -> None:
    path = STORAGE_PATH / f'{a.assessment_id}.json'
    path.write_text(a.model_dump_json(indent=2))

def get_assessment(assessment_id: str) -> Optional[FitAssessment]:
    path = STORAGE_PATH / f'{assessment_id}.json'
    if not path.exists():
        return None
    return FitAssessment.model_validate_json(path.read_text())

def list_assessments() -> list[FitAssessment]:
    results = []
    for f in STORAGE_PATH.glob('*.json'):
        try:
            results.append(FitAssessment.model_validate_json(f.read_text()))
        except Exception:
            pass    # skip malformed files silently
    return sorted(results, key=lambda a: a.created_at, reverse=True)
```

---

## 7. Test Harness

### Sample data requirements

Claude Code should generate at least **2 user profiles**, **1 resume baseline per profile**, and **5 job postings** covering these test cases:

| Test case | Expected result |
|---|---|
| Strong fit | Score 85+ |
| Borderline fit | Score 70-80 |
| Clear skip | Score below 70 |
| Eligibility failure | Score 0, hard gate triggered |
| Self-assessed gap matches hard JD requirement | Gap called out explicitly in reasoning |

### test_runner.py

```python
# test_runner.py
# Usage: python test_runner.py
import json
import httpx
from pathlib import Path

BASE_URL = 'http://localhost:8000'

def run_all():
    profiles = load_all('data/profiles')
    jobs     = load_all('data/jobs')
    resumes  = load_all('data/resumes')

    for job in jobs:
        for profile in profiles:
            print(f'\n--- {profile["profile_id"]} x {job["job_id"]} ---')
            resp = httpx.post(f'{BASE_URL}/assess', json={
                'job': job,
                'profile': profile,
                'resumes': resumes,
                'save_result': True
            }, timeout=30)
            result = resp.json()
            print(f'Score: {result["score"]}  Tier: {result["action_tier"]}')
            print(f'Confidence: {result["confidence_level"]}')
            print(f'Summary: {result["reasoning_summary"]}')
            if result['missing_signals']:
                print(f'Gaps: {result["missing_signals"]}')

def load_all(directory: str) -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in Path(directory).glob('*.json')
    ]

if __name__ == '__main__':
    run_all()
```

### Unit tests

Write tests for at minimum:

- `parse_response()` handles clean JSON, JSON with markdown fences, and malformed JSON gracefully
- `build_assessment()` correctly maps the parsed LLM response to a `FitAssessment` object
- `select_best_resume()` returns the correct baseline for an exact match, a fallback by recency, and an empty list
- The storage layer saves and retrieves an assessment correctly
- The `/assess` endpoint returns a 500 with a useful error message if the LLM call fails

---

## 8. Error Handling

| Failure | Expected behavior |
|---|---|
| LLM returns malformed JSON | Log the raw response, raise 500 with raw output in the detail field |
| LLM includes markdown fences | Strip them in `parse_response()` before attempting JSON parse |
| Pydantic validation fails on LLM output | Catch `ValidationError`, log which fields failed, raise 500. Don't return a partial object. |
| Anthropic API timeout or rate limit | Retry once after 2 seconds. If it fails again, raise 503 with a clear message. |
| Profile has missing optional fields | Expected -- Pydantic handles with `Optional` and defaults. Model sets `confidence_level = 'low'`. |
| No resume baselines provided | Score without a resume recommendation. Set `recommended_resume_id = null`, note in `confidence_reasons`. |

---

## 9. Running the Prototype

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

# Start the server
uvicorn main:app --reload

# In a separate terminal, run the test harness
python test_runner.py

# Auto-generated API docs available at:
# http://localhost:8000/docs
```

> The `/docs` endpoint renders interactive API documentation from the Pydantic schemas automatically. Use it to manually test individual assessments during development.

---

## 10. Instructions for Claude Code

Build in this order:

1. Create the project structure exactly as specified in Section 2
2. Implement `schemas.py` with all Pydantic models from Section 3 -- do not add or remove fields
3. Implement `prompts.py` with the system prompt and user prompt builder from Section 4 -- do not modify the system prompt text
4. Implement `scorer.py` with the scoring logic, LLM call, and response parsing from Section 4
5. Implement `storage.py` from Section 6
6. Implement `main.py` with all five endpoints from Section 5
7. Generate sample data: 2 user profiles, 1 resume baseline per profile, and 5 job postings covering the test cases in Section 7
8. Implement `test_runner.py` from Section 7
9. Write unit tests for the cases listed in Section 7
10. Write `README.md` with setup instructions, how to run the server, how to run tests, and how to run the test harness

### Where you have discretion

- How you name internal variables and helper functions
- How you structure the sample data files
- How you format log output in the test harness
- Adding type hints anywhere they're missing

### Where you do not have discretion

- The system prompt text in `SYSTEM_PROMPT` -- do not paraphrase or restructure it
- The output schema for `FitAssessment` -- every field must be present
- `temperature=0` on the LLM call
- The scoring formula: `score = round(competitiveness.score * 0.6 + evidence_strength.score * 0.4)`
- The action tier thresholds: `<70 skip`, `70-79 apply`, `80-89 light_tailoring`, `90-100 strong_fit`
- The project structure from Section 2

### When you're unsure

If something in the spec is ambiguous or seems like it might conflict with something else, stop and ask before implementing. Don't make assumptions that will require a rewrite to fix.
