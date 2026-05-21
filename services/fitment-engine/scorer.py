import anthropic
import json
import os
import re
import time
from datetime import datetime, timezone
from uuid import uuid4
from schemas import ScoreRequest, FitAssessment, EligibilityGate, ResumeBaseline, JobPosting, TokenUsage
from prompts import build_scoring_prompt, PROMPT_VERSION

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL  = os.getenv('MODEL', 'claude-sonnet-4-6')


def score_job(request: ScoreRequest) -> tuple[FitAssessment, TokenUsage]:
    failures = _gate_failures(request.profile, request.job)
    if failures:
        zero_usage = TokenUsage(input_tokens=0, output_tokens=0, estimated_cost_usd=0.0)
        return _build_gate_assessment(failures, request), zero_usage

    best_resume = select_best_resume(request.job, request.profile, request.resumes)
    if best_resume is None and request.profile.resume_ids:
        raise ValueError(
            f"Profile {request.profile.profile_id} has resume_ids set but "
            f"no matching resume was found in the request. Ensure the linked "
            f"resume is included in ScoreRequest.resumes."
        )
    prompt = build_scoring_prompt(request, best_resume)
    raw, usage = call_llm(prompt)
    parsed = parse_response(raw)
    parsed['eligibility'] = {'passed': True, 'reasons': []}
    result = build_assessment(parsed, request)
    return result, usage


def call_llm(prompt: dict) -> tuple[str, TokenUsage]:
    try:
        response = _make_llm_call(prompt)
    except (anthropic.APITimeoutError, anthropic.RateLimitError):
        time.sleep(2)
        response = _make_llm_call(prompt)
    return response.content[0].text, _extract_usage(response.usage)


# Sonnet 4.6 pricing as of build time ($/million tokens)
_PRICE_INPUT        = 3.00
_PRICE_OUTPUT       = 15.00
_PRICE_CACHE_WRITE  = 3.75
_PRICE_CACHE_READ   = 0.30


def _extract_usage(raw_usage) -> TokenUsage:
    cache_write = getattr(raw_usage, 'cache_creation_input_tokens', 0) or 0
    cache_read  = getattr(raw_usage, 'cache_read_input_tokens', 0) or 0
    cost = (
        raw_usage.input_tokens  * _PRICE_INPUT       / 1_000_000
        + raw_usage.output_tokens * _PRICE_OUTPUT      / 1_000_000
        + cache_write             * _PRICE_CACHE_WRITE / 1_000_000
        + cache_read              * _PRICE_CACHE_READ  / 1_000_000
    )
    return TokenUsage(
        input_tokens=raw_usage.input_tokens,
        output_tokens=raw_usage.output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        estimated_cost_usd=round(cost, 6),
    )


def _make_llm_call(prompt: dict):
    return client.messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0,          # non-negotiable -- do not change
        system=[{
            'type': 'text',
            'text': prompt['system'],
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': prompt['user']}]
    )


def parse_response(raw: str) -> dict:
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


def _skill_confirmed(profile, skill_name: str):
    for s in profile.skills:
        if s.name == skill_name:
            return s.confirmed  # True or False
    return None  # unanswered or not in skill list


def _gate_failures(profile, job) -> list[str]:
    failures = []

    min_years = _extract_min_years(job.description)
    if min_years is not None:
        gap = min_years - profile.total_years_experience
        if gap >= 3:
            failures.append(
                f'Experience gap: {profile.total_years_experience} years vs. {min_years}+ required'
            )

    if _requires_executive(job.title, job.description):
        if _skill_confirmed(profile, 'director or above leadership') is False:
            failures.append(
                'Role requires Director/VP-level leadership; candidate has confirmed they do not have it'
            )

    if _requires_onsite(job.location, job.description):
        if 'onsite' not in profile.work_arrangement and 'hybrid' not in profile.work_arrangement:
            failures.append(
                'Role requires onsite; candidate does not accept onsite or hybrid work arrangements'
            )

    non_us_country = _extract_non_us_country(job.location, job.description)
    if non_us_country:
        if _requires_onsite(job.location, job.description) or _no_sponsorship_offered(job.description):
            if profile.work_authorization in ('citizen', 'permanent_resident'):
                failures.append(
                    f'Role requires work authorization in {non_us_country}; '
                    f'candidate has US work authorization only'
                )

    if profile.requires_sponsorship and _no_sponsorship_offered(job.description):
        failures.append(
            'Role offers no visa sponsorship; candidate requires sponsorship'
        )

    return failures


def _build_gate_assessment(failures: list[str], request: ScoreRequest) -> FitAssessment:
    return FitAssessment(
        assessment_id=str(uuid4()),
        job_id=request.job.job_id,
        profile_id=request.profile.profile_id,
        prompt_version=PROMPT_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        eligibility=EligibilityGate(passed=False, reasons=failures),
        score=0,
        action_tier='skip',
        reasoning_summary=(
            'Candidate does not meet the eligibility requirements for this role. '
            + ' | '.join(failures)
        ),
        missing_signals=[],
        tailoring_suggestions=[],
        confidence_level='high',
        confidence_reasons=['Eligibility failure is deterministic based on structured profile data'],
    )


def _extract_min_years(description: str) -> int | None:
    patterns = [
        r'(\d+)\+\s*years?\s+of\s+product\s+management',
        r'(\d+)\+\s*years?\s+of\s+PM\s+experience',
        r'(\d+)\+\s*years?\s+of\s+PM\b',
        r'(\d+)\+\s*years?\s+in\s+product\s+management',
    ]
    for pat in patterns:
        m = re.search(pat, description, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _requires_executive(title: str, description: str) -> bool:
    if re.search(r'\b(VP|Vice President|Director|Chief|Head of Product)\b', title, re.IGNORECASE):
        return True
    return False


def _requires_onsite(location: str, description: str) -> bool:
    if re.search(r'\bremote\b', location, re.IGNORECASE):
        return False
    if re.search(r'\b(onsite|on-site)\b', location, re.IGNORECASE):
        return True
    if re.search(
        r'(onsite|on-site|no remote|remote work is not available|fully onsite)',
        description, re.IGNORECASE
    ):
        return True
    return False


def _no_sponsorship_offered(description: str) -> bool:
    return bool(re.search(
        r'(no visa sponsorship|does not provide\b.*\bsponsorship|sponsorship\b.*\bnot available'
        r'|no sponsorship available|must be authorized to work|right to work)',
        description, re.IGNORECASE
    ))


_INTERNATIONAL_LOCATIONS = [
    (r'\blondon\b|\bunited kingdom\b|\buk\b|\bengland\b', 'the United Kingdom'),
    (r'\btoronto\b|\bvancouver\b|\bmontreal\b|\bcalgary\b|\bcanada\b', 'Canada'),
    (r'\bsydney\b|\bmelbourne\b|\baustralia\b', 'Australia'),
    (r'\bberlin\b|\bmunich\b|\bfrankfurt\b|\bgermany\b', 'Germany'),
    (r'\bparis\b|\bfrance\b', 'France'),
    (r'\bamsterdam\b|\bnetherlands\b', 'the Netherlands'),
    (r'\bsingapore\b', 'Singapore'),
    (r'\bmumbai\b|\bbangalore\b|\bhyderabad\b|\bnew delhi\b|\bindia\b', 'India'),
]


def _extract_non_us_country(location: str, description: str) -> str | None:
    text = f'{location} {description[:300]}'
    for pattern, country in _INTERNATIONAL_LOCATIONS:
        if re.search(pattern, text, re.IGNORECASE):
            return country
    return None


def select_best_resume(
    job: JobPosting,
    profile,
    resumes: list[ResumeBaseline]
) -> ResumeBaseline | None:
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
