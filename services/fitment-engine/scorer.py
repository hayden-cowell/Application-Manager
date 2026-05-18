import anthropic
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4
from schemas import ScoreRequest, FitAssessment, ResumeBaseline, JobPosting
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
    try:
        response = _make_llm_call(prompt)
    except (anthropic.APITimeoutError, anthropic.RateLimitError):
        time.sleep(2)
        response = _make_llm_call(prompt)
    return response.content[0].text


def _make_llm_call(prompt: dict):
    return client.messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0,          # non-negotiable -- do not change
        system=prompt['system'],
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


def select_best_resume(
    job: JobPosting,
    resumes: list[ResumeBaseline]
) -> ResumeBaseline | None:
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
