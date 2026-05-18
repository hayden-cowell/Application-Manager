import json
import pytest
from unittest.mock import patch, MagicMock
from uuid import UUID

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')

from scorer import parse_response, build_assessment, select_best_resume
from schemas import (
    ScoreRequest, JobPosting, UserProfile, ResumeBaseline,
    WorkExperience, FitAssessment, EligibilityGate, ScoringComponent
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def minimal_profile():
    return UserProfile(
        profile_id='test_profile',
        target_roles=['Senior PM'],
        target_industries=['B2B SaaS'],
        work_arrangement=['remote'],
        target_company_stages=['Series B'],
        open_to_ic_and_management=True,
        job_search_urgency='active',
        total_years_experience=7,
        years_in_current_discipline=5,
        current_level='Senior PM',
        highest_level_held='Senior PM',
        leveling_trajectory='IC to Senior IC',
        has_management_experience=False,
        has_director_or_above_experience=False,
        primary_domain='B2B SaaS',
        domain_years={'B2B SaaS': 5},
        worked_at_company_stages=['Series B'],
        has_enterprise_experience=True,
        has_smb_experience=False,
        has_consumer_experience=False,
        has_0_to_1_experience=True,
        has_scaling_experience=True,
        has_platform_product_experience=True,
        has_growth_experience=False,
        can_read_code=True,
        can_write_code=False,
        comfortable_with_data=True,
        has_worked_embedded_with_engineering=True,
        has_written_technical_specs=True,
        familiarity_with_apis='medium',
        strong_in_discovery=True,
        strong_in_delivery=True,
        strong_in_strategy=True,
        strong_in_growth=False,
        has_pricing_experience=False,
        has_internationalization_experience=False,
        has_launched_products=True,
        design_collaboration_depth='medium',
        research_experience='moderate',
        has_owned_revenue_metric=True,
        has_owned_retention_metric=True,
        has_worked_with_sales=True,
        has_worked_with_legal_compliance=False,
        budget_ownership=False,
        vendor_management=False,
        country='US',
        work_authorization='citizen',
        requires_sponsorship=False,
        willing_to_relocate=False,
        current_location='Portland, OR',
        timezone='PT',
        has_exec_exposure=True,
        written_communication_strength='high',
    )


@pytest.fixture
def minimal_job():
    return JobPosting(
        job_id='test_job',
        title='Senior PM',
        company='Test Co',
        location='Remote (US)',
        description='Looking for a Senior PM with 5+ years experience in B2B SaaS.',
    )


@pytest.fixture
def sample_resume():
    return ResumeBaseline(
        resume_id='resume_platform_pm',
        name='Platform PM',
        role_type='platform',
        skills=['Product Strategy', 'API Design'],
        work_experience=[
            WorkExperience(
                company='Test Corp',
                title='Senior PM',
                start_date='2020-01',
                description='Led platform product.',
                key_achievements=['Shipped X'],
                skills_used=['Strategy'],
            )
        ],
        last_used='2026-04-01',
    )


@pytest.fixture
def valid_llm_response():
    return {
        'eligibility': {'passed': True, 'reasons': []},
        'competitiveness': {'score': 80, 'signals': ['7 years experience matches'], 'gaps': []},
        'evidence_strength': {'score': 75, 'signals': ['B2B SaaS background'], 'gaps': []},
        'score': 78,
        'action_tier': 'apply',
        'recommended_resume_id': 'resume_platform_pm',
        'reasoning_summary': 'Strong B2B SaaS background aligns well.',
        'missing_signals': [],
        'tailoring_suggestions': [],
        'confidence_level': 'high',
        'confidence_reasons': ['Complete profile, detailed JD'],
    }


# ── parse_response tests ───────────────────────────────────────────────────────

def test_parse_response_clean_json(valid_llm_response):
    raw = json.dumps(valid_llm_response)
    result = parse_response(raw)
    assert result['score'] == 78
    assert result['action_tier'] == 'apply'


def test_parse_response_strips_markdown_fences(valid_llm_response):
    raw = '```json\n' + json.dumps(valid_llm_response) + '\n```'
    result = parse_response(raw)
    assert result['score'] == 78


def test_parse_response_strips_plain_fences(valid_llm_response):
    raw = '```\n' + json.dumps(valid_llm_response) + '\n```'
    result = parse_response(raw)
    assert result['score'] == 78


def test_parse_response_raises_on_malformed():
    with pytest.raises(json.JSONDecodeError):
        parse_response('not valid json {{{')


# ── build_assessment tests ─────────────────────────────────────────────────────

def test_build_assessment_maps_fields(valid_llm_response, minimal_job, minimal_profile, sample_resume):
    request = ScoreRequest(job=minimal_job, profile=minimal_profile, resumes=[sample_resume])
    result = build_assessment(valid_llm_response, request)

    assert isinstance(result, FitAssessment)
    assert result.job_id == 'test_job'
    assert result.profile_id == 'test_profile'
    assert result.score == 78
    assert result.action_tier == 'apply'
    assert result.prompt_version == '1.0'
    assert result.user_overridden is False
    assert result.override_action is None
    # assessment_id must be a valid UUID
    UUID(result.assessment_id)
    # created_at must be an ISO timestamp
    assert 'T' in result.created_at


def test_build_assessment_eligibility_fail(minimal_job, minimal_profile, sample_resume):
    parsed = {
        'eligibility': {'passed': False, 'reasons': ['Location incompatible']},
        'competitiveness': None,
        'evidence_strength': None,
        'score': 0,
        'action_tier': 'skip',
        'recommended_resume_id': None,
        'reasoning_summary': 'Location not compatible.',
        'missing_signals': ['US work authorization'],
        'tailoring_suggestions': [],
        'confidence_level': 'high',
        'confidence_reasons': ['Clear hard fail on location'],
    }
    request = ScoreRequest(job=minimal_job, profile=minimal_profile, resumes=[sample_resume])
    result = build_assessment(parsed, request)
    assert result.score == 0
    assert result.eligibility.passed is False
    assert result.competitiveness is None


# ── select_best_resume tests ───────────────────────────────────────────────────

def test_select_best_resume_exact_match(minimal_job):
    platform_resume = ResumeBaseline(
        resume_id='r1', name='Platform PM', role_type='platform',
        skills=[], work_experience=[]
    )
    consumer_resume = ResumeBaseline(
        resume_id='r2', name='Consumer PM', role_type='consumer',
        skills=[], work_experience=[]
    )
    job = JobPosting(
        job_id='j1', title='Senior Platform PM', company='Co', location='Remote',
        description='Platform role.'
    )
    result = select_best_resume(job, [consumer_resume, platform_resume])
    assert result.resume_id == 'r1'


def test_select_best_resume_recency_fallback(minimal_job):
    older = ResumeBaseline(
        resume_id='old', name='Old', role_type='other',
        skills=[], work_experience=[], last_used='2025-01-01'
    )
    newer = ResumeBaseline(
        resume_id='new', name='New', role_type='other',
        skills=[], work_experience=[], last_used='2026-03-01'
    )
    result = select_best_resume(minimal_job, [older, newer])
    assert result.resume_id == 'new'


def test_select_best_resume_empty_list(minimal_job):
    result = select_best_resume(minimal_job, [])
    assert result is None


def test_select_best_resume_no_dates_returns_first(minimal_job):
    r1 = ResumeBaseline(resume_id='first', name='First', role_type='other', skills=[], work_experience=[])
    r2 = ResumeBaseline(resume_id='second', name='Second', role_type='other', skills=[], work_experience=[])
    result = select_best_resume(minimal_job, [r1, r2])
    assert result.resume_id == 'first'
