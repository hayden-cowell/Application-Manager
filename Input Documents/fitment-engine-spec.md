# Fitment Engine — Technical Specification

**Job Application OS | v2.0**
Stack: Python / FastAPI | LLM: Anthropic Claude Sonnet | Storage: JSON file (prototype)

> This document is the source of record for the fitment engine. It reflects all decisions made during development, including rationale for key choices. Pass to Claude Code for implementation tasks.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Data Schemas](#3-data-schemas)
4. [Scoring Logic](#4-scoring-logic)
5. [Eligibility Gate](#5-eligibility-gate)
6. [Prompt Design](#6-prompt-design)
7. [API Endpoints](#7-api-endpoints)
8. [Storage Layer](#8-storage-layer)
9. [Test Suite](#9-test-suite)
10. [Key Decisions & Rationale](#10-key-decisions--rationale)
11. [Running the Prototype](#11-running-the-prototype)
12. [Instructions for Claude Code](#12-instructions-for-claude-code)

---

## 1. Overview

The fitment engine takes a job description and a user profile and returns a structured fit assessment estimating interview likelihood. It is the core of the Job Application OS -- everything else in the product depends on this working correctly.

The prototype is a standalone Python service with a REST API, JSON file storage, and a CLI test harness. No frontend is required at this stage.

**What the engine does:**
- Runs a deterministic Python eligibility gate before any LLM call
- Scores competitive fit and evidence strength via LLM for candidates who pass eligibility
- Returns a structured assessment with score, tier, reasoning, gaps, and confidence level
- Logs overrides when users disagree with recommendations

**What the engine does not do:**
- Automate applications
- Recommend jobs
- Coach users on career strategy
- Make eligibility decisions based on skill gaps

---

## 2. Architecture

### Project structure

```
fitment-engine/
  main.py                  # FastAPI app entry point
  scorer.py                # Core scoring logic, eligibility gate, LLM calls
  prompts.py               # System prompt, profile builder, prompt assembly
  schemas.py               # Pydantic models for all data structures
  storage.py               # JSON file read/write layer
  test_runner.py           # CLI batch test harness
  data/
    profiles/              # User profiles (.json)
    jobs/                  # Job postings (.json)
    resumes/               # Resume baselines (.json)
    assessments/           # Saved assessment outputs (.json)
    test_cases/
      jd_test_expectations.json   # JD metadata and scoring expectations
    test_results/          # Timestamped run output (.json)
  tests/
    test_scorer.py         # Unit tests for scoring and eligibility logic
    test_api.py            # Integration tests for API endpoints
  requirements.txt
  .env.example
  README.md
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
httpx>=0.27.0
```

### Environment

```
# .env.example
ANTHROPIC_API_KEY=your_key_here
MODEL=claude-sonnet-4-6
PROMPT_VERSION=1.2
STORAGE_PATH=data/assessments
```

---

## 3. Data Schemas

All schemas live in `schemas.py` using Pydantic v2. These are the source of truth for data shape across the service.

### Three-state boolean system

Experience and skill fields use `Optional[bool] = null` (not plain `bool`) to represent three distinct states:

- `true` -- candidate has explicitly confirmed this experience
- `false` -- candidate has explicitly confirmed they do not have this experience
- `null` -- not yet collected; treat as unknown, do not penalize

Fields that are eligibility-critical and collected in early onboarding stay as plain `bool` because they have a meaningful default: `requires_sponsorship`, `willing_to_relocate`, `open_to_ic_and_management`, `onboarding_complete`.

This distinction matters for scoring: a candidate who hasn't answered a question yet should not be penalized the same way as one who has confirmed absence of a skill.

### UserProfile

```python
class NotableLaunch(BaseModel):
    description: str
    impact: str

class UserProfile(BaseModel):
    # Metadata
    profile_id: str
    profile_version: int = 1
    onboarding_complete: bool = False

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
    has_management_experience: Optional[bool] = None
    years_managing: Optional[int] = None
    largest_team_managed: Optional[int] = None
    has_director_or_above_experience: Optional[bool] = None

    # Domain and industry depth
    primary_domain: str
    secondary_domains: list[str] = []
    domain_years: dict[str, int]
    worked_at_company_stages: list[str]
    has_enterprise_experience: Optional[bool] = None
    has_smb_experience: Optional[bool] = None
    has_consumer_experience: Optional[bool] = None
    has_0_to_1_experience: Optional[bool] = None
    has_scaling_experience: Optional[bool] = None
    has_platform_product_experience: Optional[bool] = None
    has_growth_experience: Optional[bool] = None

    # Technical depth
    can_read_code: Optional[bool] = None
    can_write_code: Optional[bool] = None
    coding_languages: list[str] = []
    technical_background: Optional[str] = None
    comfortable_with_data: Optional[bool] = None
    data_tools: list[str] = []
    has_worked_embedded_with_engineering: Optional[bool] = None
    has_written_technical_specs: Optional[bool] = None
    familiarity_with_apis: Optional[str] = None     # 'none', 'low', 'medium', 'high'

    # Product craft
    product_areas: list[str] = []
    strong_in_discovery: Optional[bool] = None
    strong_in_delivery: Optional[bool] = None
    strong_in_strategy: Optional[bool] = None
    strong_in_growth: Optional[bool] = None
    has_pricing_experience: Optional[bool] = None
    has_internationalization_experience: Optional[bool] = None
    has_launched_products: Optional[bool] = None
    notable_launches: list[NotableLaunch] = []
    design_collaboration_depth: Optional[str] = None  # 'low', 'medium', 'high'
    research_experience: Optional[str] = None         # 'none', 'low', 'moderate', 'high'

    # Scope and impact
    largest_company_size: Optional[int] = None
    smallest_company_size: Optional[int] = None
    largest_arr_supported: Optional[str] = None
    largest_arr_supported_context: Optional[str] = None  # e.g. 'platform_pm_not_direct_owner'
    largest_dau_supported: Optional[int] = None
    has_owned_revenue_metric: Optional[bool] = None
    has_owned_retention_metric: Optional[bool] = None
    cross_functional_scope: list[str] = []
    has_worked_with_sales: Optional[bool] = None
    has_worked_with_legal_compliance: Optional[bool] = None
    budget_ownership: Optional[bool] = None
    vendor_management: Optional[bool] = None

    # Credentials and education
    highest_degree: Optional[str] = None
    degree_field: Optional[str] = None
    university_tier: Optional[str] = None
    has_mba: Optional[bool] = None
    certifications: list[str] = []
    has_published_work: Optional[bool] = None
    has_conference_speaking: Optional[bool] = None
    has_notable_side_projects: Optional[bool] = None

    # Work authorization (eligibility-critical -- plain bool)
    country: str
    work_authorization: str               # 'citizen', 'permanent_resident', 'visa', 'needs_sponsorship'
    requires_sponsorship: bool
    willing_to_relocate: bool
    current_location: str
    timezone: str

    # Soft signals
    communication_artifacts: list[str] = []
    stakeholder_management_level: Optional[str] = None
    has_exec_exposure: Optional[bool] = None
    presentation_experience: Optional[str] = None
    written_communication_strength: Optional[str] = None  # 'low', 'medium', 'high'
    self_assessed_strengths: list[str] = []
    self_assessed_gaps: list[str] = []
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
    imported_at: Optional[str] = None
```

### ResumeBaseline

```python
class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: str                       # 'YYYY-MM'
    end_date: Optional[str] = None
    company_size: Optional[int] = None
    company_stage: Optional[str] = None
    description: Optional[str] = None
    key_achievements: list[str]
    skills_used: list[str]

class ResumeBaseline(BaseModel):
    resume_id: str
    name: str
    role_type: str
    work_experience: list[WorkExperience]
    skills: list[str]
    version: int = 1
    last_used: Optional[str] = None
```

### FitAssessment (output)

```python
class EligibilityGate(BaseModel):
    passed: bool
    reasons: list[str]

class ScoringComponent(BaseModel):
    score: int
    signals: list[str]
    gaps: list[str]

class FitAssessment(BaseModel):
    assessment_id: str
    job_id: str
    profile_id: str
    prompt_version: str
    created_at: str

    eligibility: EligibilityGate
    competitiveness: Optional[ScoringComponent] = None
    evidence_strength: Optional[ScoringComponent] = None

    score: int
    action_tier: str     # 'skip', 'apply_as_is', 'apply', 'light_tailoring', 'strong_fit'
    recommended_resume_id: Optional[str] = None

    reasoning_summary: str
    missing_signals: list[str]
    tailoring_suggestions: list[str]

    confidence_level: str                 # 'low', 'medium', 'high'
    confidence_reasons: list[str]

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

class OverrideRequest(BaseModel):
    action: str                           # 'applied_anyway', 'skipped_anyway'
    note: Optional[str] = None
```

---

## 4. Scoring Logic

### scorer.py structure

```python
def score_job(request: ScoreRequest) -> FitAssessment:
    # Step 1: run Python eligibility gate
    gate_result = apply_eligibility_gate(request.job, request.profile)

    if not gate_result['passed']:
        # Return immediately -- no LLM call
        return build_failed_assessment(gate_result, request)

    # Step 2: select best resume baseline
    resume = select_best_resume(request.job, request.resumes)

    # Step 3: build prompt and call LLM
    prompt = build_scoring_prompt(request, resume)
    raw = call_llm(prompt)
    parsed = parse_response(raw)

    return build_assessment(parsed, request, gate_result)
```

### Action tiers

| Score | Tier | Meaning | Effort |
|---|---|---|---|
| < 60 | skip | Don't apply | -- |
| 60-69 | apply_as_is | Worth a shot; gaps are real and tailoring won't close them | 0 min |
| 70-79 | apply | Competitive; submit with existing resume | 0-5 min |
| 80-89 | light_tailoring | Strong fit; targeted resume edits worth doing | 5-10 min |
| 90-100 | strong_fit | Top of likely applicant pool; tailor and consider follow-up | 10-20 min |

The `apply_as_is` tier was added after initial testing showed a meaningful cluster of roles where candidates are eligible and have domain alignment but have real confirmed gaps that tailoring cannot bridge. These roles are worth submitting to for top-of-funnel volume without investing tailoring time.

### Composite score formula

```
score = round(competitiveness.score * 0.6 + evidence_strength.score * 0.4)
```

### Resume selection (deterministic, not LLM)

```python
def select_best_resume(job, resumes):
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
    return resumes[0]
```

---

## 5. Eligibility Gate

The eligibility gate runs in Python before any LLM call. If it fails, the assessment costs $0 and returns immediately. The gate checks five conditions -- nothing else.

```python
def apply_eligibility_gate(job: JobPosting, profile: UserProfile) -> dict:
    failures = []

    # Check 1: years of experience gap (sliding scale)
    min_years = extract_min_years(job.description)
    if min_years:
        gap = min_years - profile.total_years_experience
        if gap >= 3:
            failures.append(
                f"Experience gap: {profile.total_years_experience} years "
                f"vs. {min_years}+ required"
            )
        # Gap of 1-2 years: pass eligibility, carry penalty into competitiveness
        # Gap of 0-1 years: pass with no penalty

    # Check 2: executive role without confirmed leadership experience
    # Checks job.description AND job.title for executive signals
    if requires_executive(job.description, job.title):
        if profile.has_director_or_above_experience is False:
            failures.append(
                "Role requires Director/VP-level leadership; "
                "candidate has confirmed they do not have it"
            )
        # null = unknown; do not fail eligibility on unknown

    # Check 3: onsite incompatibility
    # Checks job.description AND job.location for onsite signals
    # NOTE: willing_to_relocate does NOT bypass this check.
    # Willingness to relocate means the candidate will move cities --
    # it does not mean they accept onsite work arrangements.
    if requires_onsite(job.description, job.location):
        if ('onsite' not in profile.work_arrangement
                and 'hybrid' not in profile.work_arrangement):
            failures.append(
                "Role requires onsite; candidate's work arrangement "
                "preferences do not include onsite or hybrid"
            )

    # Check 4: sponsorship incompatibility
    if profile.requires_sponsorship and no_sponsorship_offered(job.description):
        failures.append(
            "Role offers no sponsorship; candidate requires it"
        )

    # Check 5: international work authorization
    # Proxy until country-specific authorization is added to the schema.
    # Checks job.description AND job.location for non-US location signals.
    if is_international_onsite(job.description, job.location):
        if profile.work_authorization in ('citizen', 'permanent_resident'):
            country = extract_job_country(job.description, job.location)
            failures.append(
                f"Role requires work authorization in {country}; "
                f"candidate has US work authorization only"
            )

    return {
        'passed': len(failures) == 0,
        'reasons': failures
    }
```

### What is NOT an eligibility failure

The following must never fail eligibility regardless of JD language -- they belong in competitiveness scoring:

- Domain gaps (no ecommerce experience, no PLG background, no pricing ownership)
- Scale gaps (smaller ARR than preferred, smaller team size)
- Skill gaps listed under requirements or must-haves
- Confirmed_false on any experience flag
- Self-assessed gaps
- ARR, DAU, or company size mismatches

The words "non-negotiable," "required," "must-have," and "you have done X" in a JD do not expand the gate. Route them to competitiveness.

### Years gap sliding scale

| Gap | Eligibility | Competitiveness |
|---|---|---|
| 0-1 years | Pass | No penalty |
| 1-2 years | Pass | Minor penalty (carry into Step 2) |
| 3+ years | Fail | Score = 0, no LLM call |

For executive roles (Director/VP/C-level explicitly required), career stage is the gate regardless of year gap -- a candidate who has confirmed no leadership experience fails eligibility even if total years are sufficient.

---

## 6. Prompt Design

### Model selection

**Use `claude-sonnet-4-6` for all scoring calls.** Haiku was evaluated but rejected for two reasons:

1. Haiku's minimum cacheable token count is 4,096 tokens. The system prompt + profile context does not reliably clear this threshold, making caching unreliable.
2. Scoring quality on nuanced competitiveness assessments is meaningfully better on Sonnet. Haiku showed a pattern of routing domain gaps (PLG, pricing, ARR scale) to the eligibility gate despite explicit instructions not to -- this was resolved on Sonnet.

Sonnet's minimum cacheable token count is 1,024 tokens, which the system prompt clears comfortably.

### Prompt caching

Cache the system prompt via the `system` parameter -- not via user content blocks. User content block caching is not reliably supported by the current SDK and model combination.

```python
def call_llm(prompt: dict):
    return client.messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0,          # non-negotiable
        system=[{
            'type': 'text',
            'text': prompt['system'],
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': prompt['user']}]
    )
```

The system prompt + profile context combined clears the 1,024 token minimum. Cache writes fire on the first call per session and cache reads fire on all subsequent calls. This produces meaningful cost savings for multi-job scoring sessions.

### Profile compaction

Never send the full `UserProfile` as a JSON dump. Use `build_pertinent_profile()` to send only fields with scoring value. This reduced average input tokens by ~37% (from ~3,400 to ~2,200 per call) with no impact on scoring quality.

**Compaction rules:**

Always send (eligibility gate depends on these):
- `work_authorization`, `requires_sponsorship`, `willing_to_relocate`, `work_arrangement`, `current_location`, `timezone`

Always send (competitiveness core):
- `target_roles`, `total_years_experience`, `years_in_current_discipline`, `current_level`, `highest_level_held`, `primary_domain`, `domain_years`

Conditional (only if non-null and non-empty):
- `secondary_domains`, `target_industries`, `excluded_industries`
- Management block: only if `has_management_experience is True`
- Technical block: only if `can_write_code is True`
- Data block: only if `comfortable_with_data is True`
- `largest_arr_supported` + `largest_arr_supported_context` (together, inline)
- `largest_dau_supported`, `largest_company_size`
- `notable_launches`, `self_assessed_gaps`, `self_assessed_strengths`

Boolean flags compaction (three-state aware):
```python
confirmed_true = []
confirmed_false = []

flag_fields = [
    'has_0_to_1_experience', 'has_scaling_experience',
    'has_platform_product_experience', 'has_enterprise_experience',
    'has_consumer_experience', 'has_growth_experience',
    'has_pricing_experience', 'has_owned_revenue_metric',
    'has_worked_with_sales', 'has_smb_experience',
    'has_management_experience', 'can_write_code', 'comfortable_with_data',
]

for field in flag_fields:
    val = getattr(profile, field)
    if val is True:
        confirmed_true.append(field)
    elif val is False:
        confirmed_false.append(field)
    # null: omit entirely -- absence means unknown

if confirmed_true:
    d['confirmed_true'] = confirmed_true
if confirmed_false:
    d['confirmed_false'] = confirmed_false
```

Use `separators=(',', ':')` in `json.dumps()` to remove whitespace from the serialized payload.

### System prompt

```
You are a fit scoring engine for a job application tool. Your job is to evaluate
how likely a candidate is to get an interview for a specific role.

The eligibility gate has already been applied in Python. Every candidate you
evaluate has passed hard eligibility checks. Your job is to evaluate competitiveness
and evidence strength only.

STEP 1 -- COMPETITIVENESS (0-100)
Evaluate how competitive this candidate is relative to the likely applicant pool.
Consider:
- Years of relevant experience vs. what the role actually requires
- Domain and industry relevance
- Scope of previous work (ARR, company size, DAU, team size)
- Confirmed skill gaps vs. JD requirements

TENURE-RELATIVE GAP WEIGHTING -- MANDATORY:
Before penalizing a confirmed_false gap, ask: is this gap expected given the
candidate's total years of PM experience, or is it surprising?

0-3 years PM experience: absence of pricing, PLG, 0-to-1, revenue ownership,
and sales-led GTM is normal and expected. Note in missing_signals but apply
only a minor competitiveness deduction (3-5 points) unless the gap is the
single primary stated responsibility of the role.

4-6 years PM experience: absence of one or two of the above is expected.
Deduct lightly (5-8 points each) only for gaps central to the role.

7+ years PM experience: absence of core skills is a real gap at this tenure
level. Deduct 10-15 points per gap on skills that are primary responsibilities.

Always separate the experience gap penalty from the skill gap penalty.
Do not compound them. A candidate already penalized for a years gap should
not receive additional heavy penalties for skill gaps that the experience gap
already explains.

STEP 2 -- EVIDENCE STRENGTH (0-100)
Evaluate how clearly the resume supports the required skills.
Consider:
- Are required skills explicitly present in the resume?
- Are achievements measurable and specific?
- Does the resume tell a coherent story for this role?

When a JD lists a skill as a must-have AND it is the primary stated
responsibility of the role, confirmed_false carries full weight.
When a skill appears in requirements but is absent or peripheral in
responsibilities, treat confirmed_false as a minor detractor only.

EVIDENCE GAP RULE:
When a flag appears in confirmed_true but the resume contains no specific
evidence supporting it, note this in missing_signals as an evidence gap.

Format: "[Skill] — confirmed_true in profile but not evidenced in resume;
consider adding specific examples."

Weight as a minor competitiveness detractor only. confirmed_true with weak
resume evidence is not the same as confirmed_false.

STEP 3 -- COMPOSITE SCORE
score = round(competitiveness * 0.6 + evidence_strength * 0.4)

STEP 4 -- ACTION TIER
score < 60:   action_tier = 'skip'
score 60-69:  action_tier = 'apply_as_is'
score 70-79:  action_tier = 'apply'
score 80-89:  action_tier = 'light_tailoring'
score 90-100: action_tier = 'strong_fit'

STEP 5 -- CONFIDENCE
Set confidence_level based on completeness of profile data and JD signal quality.
- 'low': profile has significant missing fields, or JD is very vague
- 'medium': profile is reasonably complete, or JD has meaningful ambiguity
- 'high': profile is complete, JD is detailed, signal is clear

WORK ARRANGEMENT CONFIDENCE RULE:
If the JD does not mention work arrangement, location requirements, or
onsite/remote expectations anywhere in the text, set confidence_level to
'medium' at most and include 'Work arrangement not specified in JD' in
confidence_reasons.

Do NOT apply this rule if:
- The JD mentions remote, hybrid, or onsite anywhere in the text
- The JD lists specific office locations alongside a remote option
- The JD states travel requirements (implies remote baseline)
- The company description mentions remote-first or distributed culture

Always explain what drove the confidence level in confidence_reasons.

SPARSE PROFILE CONFIDENCE RULE:
If confirmed_true and confirmed_false combined contain fewer than 3 entries,
set confidence_level to 'medium' at most and include 'Profile flags are sparse;
score based primarily on resume and tenure signals' in confidence_reasons.

Do NOT apply this rule if:
- The profile has rich resume evidence (notable_launches, detailed work history)
- The low flag count reflects a genuinely simple profile rather than incomplete onboarding
- Confidence is already being reduced by the work arrangement rule

CRITICAL RULES:
- Do not be optimistic. Score for interview likelihood, not encouragement.
- Always cite specific phrases from the job description when identifying gaps.
- If the candidate has a self-assessed gap that the JD requires, call it out explicitly.
- tailoring_suggestions only appear if score >= 80. Return empty list otherwise.
- confirmed_false skills and self-assessed gaps are competitive weaknesses,
  not eligibility failures. Never fail eligibility in your reasoning.
- Do not use a candidate's title to infer management requirements.
  Only flag people management if it is explicitly listed as a responsibility in the JD.
- Your entire response must be valid JSON. No text outside the JSON. No markdown fences.

OUTPUT LENGTH CONSTRAINTS (mandatory):
reasoning_summary: Maximum 4 sentences. Lead with the single most important
reason the candidate is or isn't competitive. Do not restate the job title
or candidate background as an opener. No preamble.

missing_signals: Maximum 5 items. Prioritize gaps that are (a) explicitly
required in the JD and (b) confirmed_false or entirely absent from the resume.
Do not list nice-to-have gaps unless all hard requirement gaps are covered.
Each item is one line, no sub-bullets, parentheticals under 8 words.

tailoring_suggestions: Maximum 3 items. Only if score >= 80.
One sentence each, specific and actionable.

confidence_reasons: Maximum 2 items.

REQUIRED OUTPUT SCHEMA:
{
  "competitiveness": { "score": 0-100, "signals": [], "gaps": [] },
  "evidence_strength": { "score": 0-100, "signals": [], "gaps": [] },
  "score": 0-100,
  "action_tier": "skip|apply_as_is|apply|light_tailoring|strong_fit",
  "recommended_resume_id": "resume_id or null",
  "reasoning_summary": "string",
  "missing_signals": [],
  "tailoring_suggestions": [],
  "confidence_level": "low|medium|high",
  "confidence_reasons": []
}

PROFILE FIELD REFERENCE
=======================
Profile flags not present should be assumed unknown (null), not false.

Eligibility (always present in prompt):
- work_authorization: 'citizen' | 'permanent_resident' | 'visa' | 'needs_sponsorship'
- requires_sponsorship: true means employer must provide visa sponsorship
- work_arrangement: list of acceptable modes ['remote', 'hybrid', 'onsite']
- willing_to_relocate: candidate will move cities -- does NOT mean they accept onsite

Competitiveness:
- total_years_experience: total PM years across all roles
- years_in_current_discipline: years specifically in product management
- domain_years: years of experience per domain
- largest_arr_supported: largest ARR of a product they have shipped for
  -- if largest_arr_supported_context = 'platform_pm_not_direct_owner',
     treat as environmental scale signal, not direct product ownership
- largest_dau_supported, largest_company_size: scope signals

Experience flags (sent as two lists):
- confirmed_true: candidate has explicitly confirmed this experience
- confirmed_false: candidate has explicitly confirmed they do not have this experience
- Absent flags are unknown -- do not assume true or false
- If a JD strongly requires an absent flag, note in missing_signals and
  reduce confidence_level to 'medium' accordingly

Technical:
- can_write_code: can author production code (not just read it)
- familiarity_with_apis: 'low' | 'medium' | 'high' (absent = unknown)
- comfortable_with_data: fluent with data tools and SQL-level analysis

Self-assessed:
- self_assessed_gaps: explicitly cite these when the JD requires them; treat as confirmed gaps
- self_assessed_strengths: relevant when JD emphasizes areas the candidate rates highly

Scoring calibration:
- 'apply_as_is' (60-69): eligible, real domain overlap, but confirmed gaps the
  applicant pool will expose. Worth submitting; tailoring won't close the gaps.
- 'apply' (70-79): competitive candidate with at least one notable gap vs. strong applicants
- 'light_tailoring' (80-89): strong fit; targeted resume adjustments improve candidacy meaningfully
- 'strong_fit' (90-100): top 10% of likely applicant pool; matches almost all requirements
- ARR scale, PLG, pricing, and similar experience gaps reduce competitiveness score
  but NEVER fail eligibility unless JD explicitly treats them as non-negotiable gates
```

---

## 7. API Endpoints

### AssessmentResponse (API output wrapper)

The `/assess` endpoint returns an `AssessmentResponse` that wraps the assessment with token usage data. This is useful for cost tracking and debugging without requiring a separate logging layer.

```python
class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    estimated_cost_usd: float

class AssessmentResponse(BaseModel):
    assessment: FitAssessment
    usage: TokenUsage
```

### Endpoints

```python
# main.py
app = FastAPI(title='Fitment Engine', version='1.0')

@app.post('/assess', response_model=AssessmentResponse)
async def assess(request: ScoreRequest):
    try:
        result = score_job(request)        # returns AssessmentResponse
        if request.save_result:
            save_assessment(result.assessment)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/assessments', response_model=list[FitAssessment])
async def get_assessments():
    return list_assessments()

@app.get('/assessments/{assessment_id}', response_model=FitAssessment)
async def get_single(assessment_id: str):
    result = get_assessment(assessment_id)
    if not result:
        raise HTTPException(status_code=404, detail='Assessment not found')
    return result

@app.post('/assessments/{assessment_id}/override')
async def override(assessment_id: str, body: OverrideRequest):
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail='Not found')
    assessment.user_overridden = True
    assessment.override_action = body.action
    save_assessment(assessment)
    return {'status': 'logged'}

@app.get('/health')
async def health():
    return {'status': 'ok', 'prompt_version': PROMPT_VERSION}
```

---

## 8. Storage Layer

```python
# storage.py
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
            pass
    return sorted(results, key=lambda a: a.created_at, reverse=True)
```

---

## 9. Test Suite

### Test runner flags

```bash
python test_runner.py                                  # all profiles x all jobs
python test_runner.py --profile profile_hayden_cowell  # one profile x all jobs
python test_runner.py --job job_pm_workos              # all profiles x one job
python test_runner.py --profile X --job Y              # one profile x one job
```

### Output

The test runner prints a results table per run and saves a timestamped JSON to `data/test_results/`. Each call logs: score, tier, confidence, input tokens, cache_write tokens, cache_read tokens, output tokens, and estimated cost.

After each run, the runner checks results against `data/test_cases/jd_test_expectations.json` and flags:
- `must_not_happen` violations -- scans full assessment output including `missing_signals`, `reasoning_summary`, `action_tier`, `confidence_level`, and `eligibility.passed` using string matching against each entry in the `must_not_happen` list (automated)
- `expected_confidence` violations (automated)
- `expected_eligibility` violations (automated)

### JD test suite (15 jobs)

| Job ID | Category | Key test signal |
|---|---|---|
| job_agency_ecommerce_pm | domain_mismatch | MUST HAVE language should not fail eligibility |
| job_borderline | boundary | PLG + pricing gaps on SDK role |
| job_clear_skip | eligibility | VP role, career stage gate |
| job_eligibility_fail | eligibility | UK onsite, no authorization |
| job_gap_match | domain_mismatch | All three confirmed gaps match primary responsibilities |
| job_internal_ai_pm | ambiguous_arrangement | Work arrangement unstated; confidence should be medium |
| job_lead_pm_panorama_platform | strong_fit_validated | Real-world 4-round interview; must score apply or better |
| job_pm_edmunds_adtech | overqualified | 2-year minimum; confidence medium (no arrangement stated) |
| job_pm_hg_insights | requirement_bloat | 10-year minimum; confidence medium (no arrangement stated) |
| job_pm_workos | strong_fit_baseline | No stated min years; clean must-have vs. nice-to-have |
| job_principal_pm_betterhelp | b2c_required | 7+ years B2C-specific requirement |
| job_sr_manager_pm_comscore | domain_mismatch | Title implies management; JD does not require it |
| job_sr_pm_autodesk_access | boundary | Hybrid location unstated; 8-year minimum |
| job_strong_fit | strong_fit | Senior PM profile should score 85+ |
| job_tpm_cloud_platform | vague_jd | Sparse JD; onsite Beaverton |

### Profiles in test suite

| Profile ID | Description |
|---|---|
| profile_hayden_cowell | Real candidate; 3 years PM, platform/data infrastructure, ZoomInfo |
| profile_senior_pm | Synthetic; 9 years PM, developer tools, B2B SaaS, confirmed gaps in PLG and pricing |

### Error handling

| Failure | Expected behavior |
|---|---|
| LLM returns malformed JSON | Log raw response, raise 500 with raw output in detail |
| LLM includes markdown fences | Strip in `parse_response()` before JSON parse |
| Pydantic validation fails on LLM output | Catch ValidationError, log failed fields, raise 500 |
| API timeout or rate limit | Retry once after 2 seconds; raise 503 on second failure |
| Profile has null fields | Expected; Pydantic handles via Optional defaults |
| No resume baselines | Score without resume recommendation; note in confidence_reasons |

---

## 10. Key Decisions & Rationale

### Why the eligibility gate runs in Python, not the LLM

Early versions had the LLM evaluate eligibility as part of the scoring prompt. The model consistently over-applied "non-negotiable" and "required" JD language to skill gaps that belong in competitiveness scoring -- routing PLG ownership, pricing experience, and ARR scale requirements as hard eligibility failures despite explicit instructions not to.

Moving eligibility to Python made it deterministic, testable, and zero-cost on failures. The LLM now only sees candidates who have passed the gate, and the prompt focuses entirely on competitive fit.

The gate currently checks five conditions: years of experience gap, executive role without leadership experience, onsite incompatibility, sponsorship incompatibility, and international work authorization. Helper functions check both `job.description` and `job.location` / `job.title` as appropriate -- relying on description alone missed cases where the location field carried the definitive signal.

### Why Sonnet instead of Haiku

Haiku was the original model choice for cost efficiency. Two issues emerged during testing:

1. Haiku's prompt caching minimum is 4,096 tokens. The system prompt + candidate context does not reliably clear this, making cache writes inconsistent.
2. Haiku showed weaker instruction-following on the eligibility scope boundary -- routing domain gaps to the gate despite explicit rules against it. Sonnet follows the boundary correctly.

Sonnet with caching is cost-competitive with uncached Haiku for multi-job sessions. A 10-job session with Sonnet and caching active runs at approximately $0.015-0.020 per call average after the first call.

### Why `apply_as_is` tier was added

Initial scoring clustered heavily in the skip tier for real candidate profiles. Analysis showed a meaningful group of roles where the candidate is eligible and has genuine domain overlap but has confirmed gaps that tailoring cannot close. Without an intermediate tier, these roles were being scored identically to clear domain mismatches.

The `apply_as_is` tier (60-69) sets correct expectations: the role is worth a submission, tailoring won't improve odds, and the candidate should apply without over-investing. This increases top-of-funnel volume for realistic applications without encouraging false optimism.

### Why confirmed_false is separated from null in the profile

Originally all experience flags were plain `bool`. A candidate who hadn't answered "do you have pricing experience?" was treated identically to one who confirmed they don't. This unfairly penalized new users with incomplete profiles.

The three-state system (true/false/null) allows the scoring engine to:
- Penalize confirmed_false appropriately
- Treat null as unknown and note it in confidence_reasons without penalizing the score
- Improve confidence level as the profile fills in over time

### Why `willing_to_relocate` does not bypass the onsite check

Early versions short-circuited the onsite eligibility check when `willing_to_relocate` was true. This was incorrect -- willingness to relocate means a candidate will move cities, not that they accept onsite work arrangements. A remote-preferred candidate who would relocate for the right role still might not want a fully onsite position. The two signals are independent and are now checked independently.

### Why the international work authorization check is a proxy

The profile schema does not currently store country-specific work authorization. The implemented proxy infers US-only authorization from `work_authorization: citizen` or `permanent_resident` and fails eligibility when the JD specifies a non-US onsite location with no sponsorship. This is accurate for the current user base but will need to be replaced with a proper country-specific authorization field when the product expands internationally.

### Why tenure-relative gap weighting was added

Early testing showed the model compounding penalties for early-career candidates: an experience gap would reduce the score, and then confirmed_false flags on skills that require years to accumulate would reduce it further. A 3-year PM missing PLG, pricing, and 0-to-1 experience is not a weak candidate -- they simply haven't had time to accumulate those experiences.

The tenure-relative weighting treats confirmed_false gaps as expected or surprising based on career stage. Missing PLG at 3 years is normal; missing it at 9 years is a real gap. This produced meaningfully more accurate scores across test profiles.

### Why self_assessed_gaps must not duplicate confirmed_false flags

Ablation testing revealed that self_assessed_gaps overrides the null state of boolean flags. When a skill appears in self_assessed_gaps, the model treats it as confirmed absent regardless of whether the corresponding flag is null (unknown) or false (confirmed). This collapses null into false and breaks the three-state system for any skill mentioned in both places.

The fix has two parts: a signal reconciliation rule in the system prompt that defines explicit precedence (confirmed_true > confirmed_false = self_assessed_gaps > absent from all sources), and a schema convention that self_assessed_gaps should only contain nuanced gaps that do not map to a boolean flag (e.g. "executive storytelling", "regulated industry experience"). The profile builder in Phase 2 should enforce this by stripping self_assessed_gaps entries that duplicate confirmed_false flags before saving.

The original Hayden profile had "pricing and packaging" and "product-led growth" in self_assessed_gaps despite both being captured by has_pricing_experience: false and has_growth_experience: false. This caused F-N delta = 0 for those flags across all tested jobs, while flags without self_assessed_gaps overlap (has_0_to_1_experience, has_platform_product_experience) showed real non-zero F-N deltas, confirming the diagnosis.

### Why output length is constrained

Output tokens are the primary cost driver at Sonnet's pricing. Unconstrained reasoning summaries were running 1,100-1,650 tokens per call. Adding length constraints (4 sentences max for reasoning, 5 items max for gaps) reduced output tokens by ~23% with no meaningful loss in assessment quality. Users read the first two sentences of reasoning most of the time anyway.

---

## 11. Running the Prototype

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Add ANTHROPIC_API_KEY

# Start server
uvicorn main:app --reload

# Run full test suite
python test_runner.py

# Run single profile
python test_runner.py --profile profile_hayden_cowell

# API docs (auto-generated)
http://localhost:8000/docs
```

---

## 12. Instructions for Claude Code

Build or update in this order when making changes:

1. Schema changes in `schemas.py` first -- everything else depends on these
2. Prompt changes in `prompts.py` -- update system prompt text and profile builder
3. Gate changes in `scorer.py` -- eligibility logic and LLM call structure
4. API changes in `main.py` -- endpoints and response models
5. Storage changes in `storage.py` -- read/write layer
6. Test suite changes in `test_runner.py` and `data/test_cases/`

### Where you have discretion
- Internal variable names and helper functions
- Log formatting in test runner output
- Adding type hints where missing
- Error message wording

### Where you do not have discretion
- The system prompt text -- do not paraphrase, restructure, or shorten
- `temperature=0` on all LLM calls
- The scoring formula: `round(competitiveness * 0.6 + evidence_strength * 0.4)`
- The action tier thresholds: skip <60, apply_as_is 60-69, apply 70-79, light_tailoring 80-89, strong_fit 90-100
- The eligibility gate -- five checks only, nothing else; helper functions check both job.description and job.location/job.title as appropriate
- The three-state boolean compaction logic -- confirmed_true / confirmed_false / null omitted

### When you are unsure
Stop and ask before implementing. Do not make assumptions that require a rewrite to fix.