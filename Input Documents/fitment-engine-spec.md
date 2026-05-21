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
  ablation_runner.py       # Controlled ablation test harness
  data/
    profiles/              # User profiles (.json)
    jobs/                  # Job postings (.json)
    resumes/               # Resume baselines (.json)
    assessments/           # Saved assessment outputs (.json)
    test_cases/
      jd_expectations.json   # JD metadata and scoring expectations
    test_results/          # Timestamped run output (.json)
    ablation_results/      # Timestamped ablation run output (.json)
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
PROMPT_VERSION=1.4
STORAGE_PATH=data/assessments
```

---

## 3. Data Schemas

All schemas live in `schemas.py` using Pydantic v2. These are the source of truth for data shape across the service.

### Three-state skill system

Skills use the `Skill` model rather than individual `Optional[bool]` fields to represent three distinct states:

- `Skill(confirmed=True)` -- candidate has explicitly confirmed they have this skill
- `Skill(confirmed=False)` -- candidate has explicitly confirmed they do not have this skill
- Skill name in `unanswered_skills` -- not yet collected; treat as unknown, do not penalize

Fields that are eligibility-critical and collected in early onboarding stay as plain `bool` because they have a meaningful default: `requires_sponsorship`, `willing_to_relocate`, `open_to_ic_and_management`, `onboarding_complete`.

This distinction matters for scoring: a candidate who hasn't answered a question yet should not be penalized the same way as one who has confirmed absence of a skill.

### UserProfile

```python
class NotableLaunch(BaseModel):
    description: str
    impact: str

class Skill(BaseModel):
    name: str
    confirmed: bool    # True = has it, False = confirmed absent

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
    years_managing: Optional[int] = None
    largest_team_managed: Optional[int] = None

    # Domain and industry depth
    primary_domain: str
    secondary_domains: list[str] = []
    domain_years: dict[str, int]
    worked_at_company_stages: list[str]

    # Technical depth (structured supplements -- populated when relevant skills are confirmed)
    coding_languages: list[str] = []
    technical_background: Optional[str] = None
    data_tools: list[str] = []
    familiarity_with_apis: str             # 'none', 'low', 'medium', 'high'

    # Product craft
    product_areas: list[str] = []
    notable_launches: list[NotableLaunch] = []
    design_collaboration_depth: str        # 'low', 'medium', 'high'
    research_experience: str               # 'none', 'low', 'moderate', 'high'

    # Scope and impact
    largest_company_size: Optional[int] = None
    smallest_company_size: Optional[int] = None
    largest_arr_supported: Optional[str] = None
    largest_arr_supported_context: Optional[str] = None  # e.g. 'platform_pm_not_direct_owner'
    largest_dau_supported: Optional[int] = None
    cross_functional_scope: list[str] = []

    # Credentials and education
    highest_degree: Optional[str] = None
    degree_field: Optional[str] = None
    university_tier: Optional[str] = None
    certifications: list[str] = []

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
    presentation_experience: Optional[str] = None
    written_communication_strength: str   # 'low', 'medium', 'high'
    self_assessed_strengths: list[str] = []

    # self_assessed_gaps: free-form weaknesses the candidate volunteers.
    # Must NOT duplicate skills already in confirmed_false (i.e. skills with
    # confirmed=False). Duplication causes self_assessed_gaps to override the
    # unanswered state of skills, collapsing unknown into absent and breaking
    # the three-state system. Use only for nuanced gaps that don't map to a
    # named skill (e.g. "executive storytelling", "regulated industry experience").
    # The profile builder (Phase 2) should strip self_assessed_gaps entries
    # that duplicate confirmed_false skills before saving.
    self_assessed_gaps: list[str] = []

    # Skill list (replaces PM-specific boolean flags)
    # confirmed=True: has this skill; confirmed=False: confirmed absent
    skills: list[Skill] = []
    # Skills not yet collected (null / unknown state)
    unanswered_skills: list[str] = []

    # Linked resumes
    resume_ids: list[str] = []            # ordered list of resume_ids belonging to this profile

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
    profile_id: Optional[str] = None      # links this resume to a specific profile; null for unlinked/legacy resumes
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
def score_job(request: ScoreRequest) -> tuple[FitAssessment, TokenUsage]:
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
def select_best_resume(job, profile, resumes):
    if not profile.resume_ids:
        return None

    # Filter to resumes explicitly linked to this profile
    profile_resumes = [r for r in resumes if r.resume_id in profile.resume_ids]

    if not profile_resumes:
        return None

    # Match on role_type against job title
    job_title_lower = job.title.lower()
    for resume in profile_resumes:
        if resume.role_type.lower() in job_title_lower:
            return resume

    # Fall back to most recently used linked resume
    with_dates = [r for r in profile_resumes if r.last_used]
    if with_dates:
        return sorted(with_dates, key=lambda r: r.last_used, reverse=True)[0]

    return profile_resumes[0]
```

Resumes are linked to profiles via `profile_id` on `ResumeBaseline` and `resume_ids` on `UserProfile`. `select_best_resume()` filters to linked resumes only — no fallback to unlinked resumes. When building the Phase 2 resume parser, set `profile_id` on the produced `ResumeBaseline` and append the `resume_id` to `profile.resume_ids`.
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
- Supplemental context blocks (tied to skill confirmation):
  - `years_managing`, `largest_team_managed` when 'people management' is confirmed
  - `coding_languages`, `technical_background` when 'software development' is confirmed
  - `data_tools` when 'data analysis' is confirmed
- `largest_arr_supported` + `largest_arr_supported_context` (together, inline)
- `largest_dau_supported`, `largest_company_size`
- `notable_launches`, `self_assessed_gaps`, `self_assessed_strengths`

Skill list compaction (three-state aware):
```python
confirmed_present = [s.name for s in profile.skills if s.confirmed]
confirmed_absent  = [s.name for s in profile.skills if not s.confirmed]
unknown_skills    = profile.unanswered_skills

# Supplemental fields for skills that carry structured context
_skill_names = {s.name for s in profile.skills if s.confirmed}
if 'people management' in _skill_names:
    d['years_managing'] = profile.years_managing
    d['largest_team_managed'] = profile.largest_team_managed
if 'software development' in _skill_names:
    d['coding_languages'] = profile.coding_languages
    d['technical_background'] = profile.technical_background
if 'data analysis' in _skill_names:
    d['data_tools'] = profile.data_tools

if confirmed_present:
    d['confirmed_true'] = confirmed_present
if confirmed_absent:
    d['confirmed_false'] = confirmed_absent
if unknown_skills:
    d['unanswered'] = unknown_skills
```

The prompt receives the same `confirmed_true` / `confirmed_false` / `unanswered` keys as before -- only the source changed from hardcoded field names to dynamic skill names.

Use `separators=(',', ':')` in `json.dumps()` to remove whitespace from the serialized payload.

### System prompt

```
You are a fit scoring engine for a job application tool. Your job is to evaluate
how competitive a candidate is for a role and how likely they are to get an interview.
Eligibility screening (work authorization, location, experience minimums) is handled
externally — assume the candidate has already passed the eligibility gate.

You must follow this exact evaluation process:

STEP 1 -- COMPETITIVENESS
Evaluate how competitive the candidate is relative to the likely applicant pool.
Consider:
- Years of relevant experience vs. what the role actually requires (not just the minimum)
- Domain and industry relevance
- Scope of previous work (company size, ARR, DAU, team size)
- Confirmed skill gaps vs. JD requirements (cite specific JD phrases when flagging gaps)
Score 0-100. Most evaluated candidates will score 50-80 here.

STEP 2 -- EVIDENCE STRENGTH
Evaluate how clearly the resume supports the required skills.
Consider:
- Are the required skills explicitly present in the resume?
- Are achievements measurable and specific?
- Does the resume tell a coherent story for this type of role?
Score 0-100.

EVIDENCE GAP RULE:
When a flag appears in confirmed_true but the resume contains no specific
evidence supporting it -- no relevant achievements, tools, or role descriptions
that corroborate the claimed experience -- note this explicitly in
missing_signals as an evidence gap rather than treating the flag as full
corroboration.

Format: "[Skill] — confirmed_true in profile but not evidenced in resume;
consider adding specific examples."

This applies most commonly when:
- A candidate claims has_platform_product_experience: true but resume shows
  only consumer or internal tooling work
- A candidate claims has_growth_experience: true but resume has no
  experimentation or funnel metrics
- A candidate claims can_write_code: true but resume has no technical
  achievements or tool evidence

Weight evidence gaps as minor competitiveness detractors only. The candidate
has confirmed the experience -- the gap is in resume presentation, not
necessarily in reality. Do not treat confirmed_true with weak evidence the
same as confirmed_false.

STEP 3 -- COMPOSITE SCORE
score = round(competitiveness.score * 0.6 + evidence_strength.score * 0.4)

STEP 4 -- ACTION TIER
- score < 60:   action_tier = 'skip'
- score 60-69:  action_tier = 'apply_as_is'
- score 70-79:  action_tier = 'apply'
- score 80-89:  action_tier = 'light_tailoring'
- score 90-100: action_tier = 'strong_fit'

STEP 5 -- CONFIDENCE
Set confidence_level based on:
- 'low': profile has significant missing fields, or JD is vague/sparse
- 'medium': profile is reasonably complete, JD has some ambiguity
- 'high': profile is complete, JD is detailed, match or mismatch is clear
Always explain what drove the confidence level in confidence_reasons.
If the job description does not mention work arrangement, location, or onsite/remote
expectations anywhere in the text, this is missing eligibility-relevant information.
Set confidence_level to 'medium' at most and include 'Work arrangement not specified
in JD' in confidence_reasons regardless of how complete the profile is or how clear
the fit signal is.

SPARSE PROFILE CONFIDENCE RULE:
If the candidate profile contains fewer confirmed_true or confirmed_false
flags than confirmed skill signals would justify -- specifically if both
confirmed_true and confirmed_false are absent or contain fewer than 3 entries
combined -- set confidence_level to 'medium' at most and include 'Profile
flags are sparse; score based primarily on resume and tenure signals' in
confidence_reasons.

Do NOT apply this rule if:
- The profile has rich resume evidence (notable_launches, work history,
  detailed product_areas)
- The low flag count reflects a genuinely simple profile rather than
  incomplete onboarding
- Confidence is already being reduced by the work arrangement rule

SIGNAL RECONCILIATION:
When confirmed_true/confirmed_false flags and self_assessed_gaps contain
overlapping information, resolve conflicts as follows:

- confirmed_true takes precedence over self_assessed_gaps. If a skill
  appears in confirmed_true AND in self_assessed_gaps, treat it as
  confirmed present. The structured flag is a direct answer to a specific
  question and overrides a general self-assessment.

- confirmed_false is consistent with self_assessed_gaps. If a skill
  appears in confirmed_false AND in self_assessed_gaps, treat it as
  confirmed absent. The self_assessed_gap is corroborating evidence.

- If a skill is absent from both confirmed lists but appears in
  self_assessed_gaps, treat it as confirmed absent for scoring purposes.
  The candidate has explicitly identified it as a weakness.

- If a skill is absent from all three sources (confirmed_true,
  confirmed_false, self_assessed_gaps), treat it as unknown. Do not
  penalize. Note in missing_signals if the JD strongly requires it and
  reduce confidence_level to medium accordingly.

CRITICAL RULES:
- Do not be optimistic. Score for interview likelihood, not for encouragement.
- Always cite specific phrases from the job description when identifying gaps.
- If the candidate has a self-assessed gap that the JD requires, call it out explicitly.
- tailoring_suggestions should only be populated if score >= 80. Return empty list otherwise.
- confirmed_false on an experience flag means the candidate has confirmed they lack it.
  Before penalizing, ask: is this gap expected given the candidate's years_in_current_discipline,
  or is it surprising for someone at that tenure level?

  EXPECTED GAPS — note in missing_signals but do not add competitiveness points beyond what
  the experience gap already reflects:
  - 0-3 years PM: absence of pricing, PLG, 0-to-1, revenue ownership, or sales-led GTM
    is normal. These skills take time to accumulate and their absence is explained by tenure.
  - 4-6 years PM: absence of one or two of the above is expected. Deduct lightly
    (3-5 points per gap) only for skills that are the primary stated job responsibility.

  SURPRISING GAPS — penalize at full weight:
  - 7+ years PM: a senior PM missing core skills the role requires is a real competitive gap.
    Deduct 10-15 points per skill that is a primary responsibility in this specific role.

  Always separate the experience gap penalty from the skill gap penalty. Do not compound them.
  If the experience gap already reflects limited tenure, do not then add further deductions
  for the predictable gaps that come with that tenure.

  JD CENTRALITY: A confirmed_false gap carries full weight only when the skill is both listed
  as a must-have AND appears prominently across multiple responsibility bullets. When a skill
  appears in requirements but is peripheral or absent from the responsibilities section,
  treat confirmed_false as a minor detractor regardless of tenure.
OUTPUT LENGTH CONSTRAINTS (mandatory):
- reasoning_summary: Maximum 4 sentences. Lead with the single most important reason
  the candidate is or isn't competitive. Do not open with the job title or candidate
  background — get directly to the fit assessment.
- missing_signals: Maximum 5 items. Prioritize gaps that are (a) explicitly required
  in the JD and (b) confirmed_false or entirely absent from the resume. Do not list
  nice-to-have gaps unless all hard requirement gaps are already covered. One line per
  item, no sub-bullets, no parenthetical explanations longer than 8 words.
- tailoring_suggestions: Maximum 3 items. Only populated if score >= 80. One sentence
  each, specific and actionable.
- confidence_reasons: Maximum 2 items.
Do not pad any field to appear thorough. Shorter is better if the signal is the same.
- Your entire response must be valid JSON. No text outside the JSON object. No markdown fences.

REQUIRED OUTPUT SCHEMA:
{
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
  "action_tier": "skip | apply_as_is | apply | light_tailoring | strong_fit",
  "recommended_resume_id": "resume_id or null",
  "reasoning_summary": "2-4 sentence plain English explanation",
  "missing_signals": ["thing 1", "thing 2"],
  "tailoring_suggestions": ["suggestion 1"],
  "confidence_level": "low | medium | high",
  "confidence_reasons": ["reason 1"]
}

PROFILE FIELD REFERENCE
=======================
Profile fields not present in the candidate context should be assumed unknown (null) -- do not penalize for absent flags.

Competitiveness fields:
- total_years_experience: total PM years across all roles
- years_in_current_discipline: years specifically in product management
- domain_years: years of experience per domain -- use this for depth claims, not just primary_domain
- largest_arr_supported: largest ARR of a product they have personally shipped for
- largest_dau_supported: largest active user base on a product they owned
- largest_company_size: headcount at largest employer
- has_management_experience / years_managing / largest_team_managed: people leadership depth
- has_director_or_above_experience: has held Director, VP, or C-level title

Experience flags:
- confirmed_true: candidate has explicitly confirmed they have this experience
- confirmed_false: candidate has explicitly confirmed they do not have this experience
- Absent flags are unknown — do not assume true or false; if the JD strongly requires an
  absent flag, note it in missing_signals and reduce confidence_level to 'medium' accordingly
- has_0_to_1_experience: has built net-new products from scratch
- has_scaling_experience: has grown existing products at scale
- has_platform_product_experience: has built platform or API products (not just consumed them)
- has_enterprise_experience / has_smb_experience / has_consumer_experience: segment exposure
- has_growth_experience: has owned PLG funnels, activation loops, or A/B growth experiments
- has_pricing_experience: has made a packaging or pricing tier decision for a product
- has_owned_revenue_metric: has been directly accountable for a revenue number
- has_worked_with_sales: has collaborated in sales-assisted or sales-led GTM motions
- has_management_experience / can_write_code / comfortable_with_data: also use confirmed_true/false

Technical fields:
- can_write_code: can author production code, not just read it
- familiarity_with_apis: 'low' | 'medium' | 'high' (absent = none)
- comfortable_with_data: fluent with data tools and SQL-level analysis

Self-assessed fields:
- self_assessed_gaps: treat as confirmed gaps -- cite them explicitly when the JD requires them
- self_assessed_strengths: weight appropriately when the JD emphasizes matching areas

Scoring calibration:
- 'apply_as_is' (60-69): gaps are real and tailoring won't close them, but domain alignment
  makes the role worth a shot; submit resume as-is with clear-eyed expectations
- 'apply' (70-79): competitive but at least one notable gap vs. strong applicants
- 'light_tailoring' (80-89): strong fit; targeted resume changes would meaningfully improve it
- 'strong_fit' (90-100): top 10% of the likely applicant pool; matches almost all requirements
- confirmed_false on a core skill is a competitive gap, not a disqualifier; weight it
  relative to tenure (see CONFIRMED_FALSE PENALTY GUIDANCE above)
```

---

## 7. API Endpoints

### AssessmentResponse (API output wrapper)

The `/assess` endpoint returns an `AssessmentResponse` that wraps the assessment with token usage data. This is useful for cost tracking and debugging without requiring a separate logging layer.

```python
class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    estimated_cost_usd: float

class AssessmentResponse(BaseModel):
    assessment: FitAssessment
    token_usage: TokenUsage
```

### Endpoints

```python
# main.py
app = FastAPI(title='Fitment Engine', version='1.0')

@app.post('/assess', response_model=AssessmentResponse)
async def assess(request: ScoreRequest):
    try:
        assessment, token_usage = score_job(request)
        if request.save_result:
            save_assessment(assessment)
        return AssessmentResponse(assessment=assessment, token_usage=token_usage)
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

### Ablation runner flags

```bash
python ablation_runner.py                   # all three categories
python ablation_runner.py --category 1      # sparse vs. full profile
python ablation_runner.py --category 2      # flag ablation (three-state validation)
python ablation_runner.py --category 3      # cross-profile comparison
```

### Output

The test runner prints a results table per run and saves a timestamped JSON to `data/test_results/`. Each call logs: score, tier, confidence, input tokens, cache_write tokens, cache_read tokens, output tokens, and estimated cost.

After each run, the runner checks results against `data/test_cases/jd_expectations.json` and flags:
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

| Profile ID | Description | Resume |
|---|---|---|
| profile_hayden_cowell | Real candidate; 3 years PM, platform/data infrastructure, ZoomInfo | resume_hayden_cowell_platform_pm |
| profile_senior_pm | Synthetic; 9 years PM, developer tools, B2B SaaS, confirmed gaps in PLG and pricing, has 0-to-1 | resume_platform_pm |
| profile_midcareer_pm | Synthetic; 8 years PM, B2B SaaS and consumer, confirmed true on PLG/pricing/growth/revenue | resume_midcareer_pm_generalist |
| profile_senior_tpm | Synthetic; 10 years TPM, cross-functional software delivery, thin resume skills section, confirmed gap in pricing | resume_senior_tpm |
| profile_hayden_sparse | Sparse variant of Hayden; all Optional flags null, simulates day-one user. Built dynamically in ablation_runner -- no static file. | resume_hayden_cowell_platform_pm |

### Ablation findings summary

Ablation testing (May 2026) produced the following key findings:

**Three-state system is working correctly.** Flags with no self_assessed_gaps overlap show non-zero F-N deltas: `has_0_to_1_experience` showed F-N of -9 on WorkOS, `has_platform_product_experience` showed F-N of -4 on Panorama. Flags without this property (has_growth_experience, has_pricing_experience) showed F-N=0 due to self_assessed_gaps interference -- resolved by the signal reconciliation rule.

**Resume dominates scoring.** Average delta between sparse and full Hayden profile across 15 jobs was only 3 points. The structured profile flags add precision at the margins; the resume text carries the primary scoring signal. This validates the resume-first onboarding approach for Phase 2.

**Flags most impactful on scores:** `has_platform_product_experience` (T-F delta 6-10 on platform roles), `has_0_to_1_experience` (T-F delta 5-9 on roles where it is a must-have), `has_pricing_experience` (T-F delta 10 on monetization roles).

**Cross-profile ranking on job_strong_fit:** Hayden scores above senior_tpm despite less tenure because senior_tpm has `can_write_code: false` and a thin resume -- the job explicitly requires coding ability. This is correct behavior, not a ranking violation.

**1-point score inversions are rounding artifacts.** The composite formula `round(competitiveness * 0.6 + evidence_strength * 0.4)` can produce 1-point differences in either direction when underlying components are nearly identical. Meaningful signal threshold is 3+ points in a consistent direction.

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

Evidence: flags with self_assessed_gaps overlap (has_growth_experience, has_pricing_experience) showed F-N delta = 0 across all tested jobs. Flags without overlap (has_0_to_1_experience, has_platform_product_experience) showed real non-zero F-N deltas.

The fix has two parts: a signal reconciliation rule in the system prompt that defines explicit precedence (confirmed_true > confirmed_false = self_assessed_gaps > absent from all sources), and a schema convention that self_assessed_gaps should only contain nuanced gaps that do not map to a boolean flag. The profile builder in Phase 2 should enforce this by stripping self_assessed_gaps entries that duplicate confirmed_false flags before saving.

### Why the evidence gap rule was added

Ablation testing revealed that the scoring engine treated confirmed_true flags as full corroboration even when the resume had no supporting evidence. The senior_tpm profile (confirmed_true on platform and growth experience, thin resume with no specific tools listed) was scoring lower than expected because evidence strength was penalized without a clear signal about why.

The evidence gap rule makes the distinction explicit: confirmed_true with weak resume evidence is not the same as confirmed_false. The gap is in resume presentation, not skill absence. This surfaces as a minor missing_signals note ("consider adding specific examples") rather than a competitiveness penalty, giving users actionable feedback rather than an unexplained score deduction.

### Why test_runner.py uses explicit resume mapping

`select_best_resume()` matches on role_type against job title. When multiple resumes with generic role_types (e.g. "product manager") are present in `data/resumes/`, the wrong resume can be selected for a given profile. This was discovered when Hayden's scores were being calculated against the midcareer PM generalist resume instead of his platform PM resume, producing meaningfully different (and incorrect) assessments.

The `PROFILE_RESUME_MAP` in `test_runner.py` bypasses role_type matching for known profiles, ensuring each profile always uses its correct resume. Any new profile added to the test suite must have a corresponding entry in this map.

### Why self_assessed_gaps overriding null was discovered late

The original test profiles were built with self_assessed_gaps entries that duplicated confirmed_false flags. This masked the three-state system's behavior for those flags throughout initial testing. The issue was only diagnosed during structured ablation testing when F-N deltas were measured explicitly. The fix -- removing duplicate entries from self_assessed_gaps and adding the signal reconciliation rule -- resolved the issue and confirmed the three-state system works correctly for flags without self_assessed_gaps overlap.

### Why output length is constrained

Output tokens are the primary cost driver at Sonnet's pricing. Unconstrained reasoning summaries were running 1,100-1,650 tokens per call. Adding length constraints (4 sentences max for reasoning, 5 items max for gaps) reduced output tokens by ~23% with no meaningful loss in assessment quality. Users read the first two sentences of reasoning most of the time anyway.

### Why resumes are explicitly linked to profiles

The original implementation used a hardcoded `PROFILE_RESUME_MAP` in the test harness to work around role_type matching failures when multiple resumes were present. In a multi-user system this approach breaks down — falling back to unlinked resumes risks scoring against another user's resume, which is both incorrect and a privacy problem.

Resumes are now linked to profiles via `profile_id` on `ResumeBaseline` and `resume_ids` on `UserProfile`. If no linked resume is found the scorer returns a 400 error. The correct resolution is to collect a resume from the user via the Phase 2 resume parser or manual upload before scoring can proceed.

### Why the profile schema was migrated to a role-agnostic skill list

The original schema used PM-specific boolean flags (`has_pricing_experience`, `has_growth_experience`, etc.). This created two problems: the schema was not portable to other role types (SWE, designer, data scientist), and adding a new role type would require schema migrations, new onboarding flows, and new prompt logic for every discipline added.

The skill list approach replaces boolean flags with a list of named skills, each with a confirmed boolean. The three-state system (true/false/null) is preserved: `confirmed=True` means has it, `confirmed=False` means confirmed absent, and presence in `unanswered_skills` means not yet collected. The prompt receives the same `confirmed_true`/`confirmed_false`/`unanswered` structure as before -- only the source of that data changed from hardcoded flag names to dynamic skill names. This makes the schema role-agnostic: PM skills, SWE skills, and designer skills all use the same `Skill` model. New disciplines add skills to the question bank without touching the schema.

The migration from boolean flags to skill entries is lossless: each flag maps to a canonical skill name, and the confirmed/None/False state maps directly to the three-state representation.

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

# Run ablation tests
python ablation_runner.py --category 2

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
7. Update `PROFILE_RESUME_MAP` in `test_runner.py` when adding new profiles

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
- `PROFILE_RESUME_MAP` entries for existing profiles -- do not change without explicit instruction

### When you are unsure
Stop and ask before implementing. Do not make assumptions that require a rewrite to fix.