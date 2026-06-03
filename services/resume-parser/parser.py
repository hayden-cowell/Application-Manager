import anthropic
import json
import logging
import os
import time
from uuid import uuid4

# schemas resolves to services/fitment-engine/schemas.py via sys.path (set in main.py)
from schemas import UserProfile, ResumeBaseline, Skill, WorkExperience, NotableLaunch  # type: ignore
from parse_prompts import CALL1_SYSTEM, CALL2_SYSTEM, build_call1_user_prompt, build_call2_user_prompt

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
MODEL  = os.getenv('MODEL', 'claude-sonnet-4-6')

# Fields that cannot be inferred from a resume — always collected via followup
ALWAYS_FOLLOWUP = [
    'work_arrangement',
    'target_industries',
    'target_company_stages',
    'open_to_ic_and_management',
    'job_search_urgency',
    'work_authorization',
    'requires_sponsorship',
    'willing_to_relocate',
    'self_assessed_gaps',
    'country',
    'timezone',
]

# Safe defaults used until the user fills in the followup fields
UNINFERRABLE_DEFAULTS = {
    'target_industries': [],
    'work_arrangement': [],
    'target_company_stages': [],
    'open_to_ic_and_management': False,
    'job_search_urgency': 'open',
    'work_authorization': 'unknown',
    'requires_sponsorship': False,
    'willing_to_relocate': False,
    'country': '',
    'timezone': '',
}

# Inferrable required fields whose absence should also go into followup
INFERRABLE_REQUIRED = [
    'target_roles',
    'total_years_experience',
    'years_in_current_discipline',
    'current_level',
    'highest_level_held',
    'leveling_trajectory',
    'primary_domain',
    'domain_years',
    'familiarity_with_apis',
    'design_collaboration_depth',
    'research_experience',
    'current_location',
    'written_communication_strength',
]


def build_message_content(input_type: str, content: str, user_prompt: str) -> list:
    if input_type == 'pdf':
        return [
            {
                'type': 'document',
                'source': {
                    'type': 'base64',
                    'media_type': 'application/pdf',
                    'data': content,
                },
            },
            {
                'type': 'text',
                'text': user_prompt,
            },
        ]
    return [{'type': 'text', 'text': f'{user_prompt}\n\n{content}'}]


def _call_llm(system_prompt: str, message_content: list) -> str:
    def _make_call():
        return client.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=[{
                'type': 'text',
                'text': system_prompt,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': message_content}],
        )

    try:
        response = _make_call()
    except (anthropic.APITimeoutError, anthropic.RateLimitError):
        time.sleep(2)
        response = _make_call()

    return response.content[0].text


def _parse_json_response(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1].rsplit('```', 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error('LLM returned malformed JSON: %s', raw[:500])
        raise


def evaluate_parse_quality(profile: UserProfile, resume: ResumeBaseline) -> str:
    if len(resume.work_experience) < 2 or not profile.total_years_experience:
        return 'low'

    has_dates = all(w.start_date for w in resume.work_experience)
    achievement_count = sum(len(w.key_achievements) for w in resume.work_experience)

    if has_dates and achievement_count >= 3 and profile.current_location and profile.skills:
        return 'high'

    if profile.primary_domain and profile.current_level:
        return 'medium'

    return 'low'


def parse_resume(
    input_type: str,
    content: str,
) -> tuple[UserProfile, ResumeBaseline, str, list[str], list[str]]:
    """
    Returns: (profile, resume, parse_quality, parse_warnings, fields_requiring_followup)
    Raises ValueError for PDF document block failures (→ 400 in main.py).
    Raises json.JSONDecodeError for malformed LLM responses (→ 500 in main.py).
    """
    warnings: list[str] = []

    # --- Call 1: universal profile fields + work experience ---
    call1_content = build_message_content(input_type, content, build_call1_user_prompt())
    try:
        raw1 = _call_llm(CALL1_SYSTEM, call1_content)
    except anthropic.BadRequestError as e:
        raise ValueError(
            'PDF could not be processed. Try pasting as plain text.'
        ) from e

    data1 = _parse_json_response(raw1)
    profile_data = data1.get('profile', {})
    resume_data  = data1.get('resume', {})

    # --- Call 2: skill classification ---
    call2_content = build_message_content(input_type, content, build_call2_user_prompt())
    try:
        raw2 = _call_llm(CALL2_SYSTEM, call2_content)
    except anthropic.BadRequestError as e:
        raise ValueError(
            'PDF could not be processed. Try pasting as plain text.'
        ) from e

    data2 = _parse_json_response(raw2)

    # --- Build Skill list from Call 2 output ---
    skills = (
        [Skill(name=n, confirmed=True)  for n in data2.get('confirmed_true', [])]
        + [Skill(name=n, confirmed=False) for n in data2.get('confirmed_false', [])]
    )
    unanswered_skills = data2.get('unanswered', [])

    # --- Generate IDs and link profile ↔ resume ---
    profile_id = f'profile_{uuid4().hex[:8]}'
    resume_id  = f'resume_{uuid4().hex[:8]}'

    # --- Apply defaults for uninferrable required fields ---
    merged = {**UNINFERRABLE_DEFAULTS, **{k: v for k, v in profile_data.items() if v is not None}}

    # Build work experience list
    work_exp = []
    for we in resume_data.get('work_experience', []):
        try:
            work_exp.append(WorkExperience(
                company=we.get('company', ''),
                title=we.get('title', ''),
                start_date=we.get('start_date', ''),
                end_date=we.get('end_date'),
                company_size=we.get('company_size'),
                company_stage=we.get('company_stage'),
                description=we.get('description', ''),
                key_achievements=we.get('key_achievements', []),
                skills_used=we.get('skills_used', []),
            ))
        except Exception:
            warnings.append(f'Could not parse work experience entry: {we.get("company", "unknown")}')

    # Build notable launches list
    notable_launches = []
    for nl in merged.get('notable_launches', []):
        if isinstance(nl, dict):
            try:
                notable_launches.append(NotableLaunch(
                    description=nl.get('description', ''),
                    impact=nl.get('impact', ''),
                ))
            except Exception:
                pass

    # --- Construct UserProfile ---
    profile = UserProfile(
        profile_id=profile_id,
        target_roles=merged.get('target_roles') or [],
        target_industries=merged.get('target_industries') or [],
        excluded_industries=[],
        work_arrangement=merged.get('work_arrangement') or [],
        target_company_stages=merged.get('target_company_stages') or [],
        open_to_ic_and_management=merged.get('open_to_ic_and_management', False),
        job_search_urgency=merged.get('job_search_urgency') or 'open',
        total_years_experience=merged.get('total_years_experience') or 0,
        years_in_current_discipline=merged.get('years_in_current_discipline') or 0,
        current_level=merged.get('current_level') or '',
        highest_level_held=merged.get('highest_level_held') or '',
        leveling_trajectory=merged.get('leveling_trajectory') or 'varied',
        years_managing=merged.get('years_managing'),
        largest_team_managed=merged.get('largest_team_managed'),
        primary_domain=merged.get('primary_domain') or '',
        secondary_domains=merged.get('secondary_domains') or [],
        domain_years=merged.get('domain_years') or {},
        worked_at_company_stages=merged.get('worked_at_company_stages') or [],
        coding_languages=merged.get('coding_languages') or [],
        technical_background=merged.get('technical_background'),
        data_tools=merged.get('data_tools') or [],
        familiarity_with_apis=merged.get('familiarity_with_apis') or 'none',
        product_areas=merged.get('product_areas') or [],
        notable_launches=notable_launches,
        design_collaboration_depth=merged.get('design_collaboration_depth') or 'low',
        research_experience=merged.get('research_experience') or 'none',
        largest_company_size=merged.get('largest_company_size'),
        largest_arr_supported=merged.get('largest_arr_supported'),
        largest_arr_supported_context=merged.get('largest_arr_supported_context'),
        largest_dau_supported=merged.get('largest_dau_supported'),
        cross_functional_scope=merged.get('cross_functional_scope') or [],
        highest_degree=merged.get('highest_degree'),
        degree_field=merged.get('degree_field'),
        university_tier=merged.get('university_tier'),
        country=merged.get('country') or '',
        work_authorization=merged.get('work_authorization') or 'unknown',
        requires_sponsorship=merged.get('requires_sponsorship', False),
        willing_to_relocate=merged.get('willing_to_relocate', False),
        current_location=merged.get('current_location') or '',
        timezone=merged.get('timezone') or '',
        communication_artifacts=merged.get('communication_artifacts') or [],
        stakeholder_management_level=merged.get('stakeholder_management_level'),
        presentation_experience=merged.get('presentation_experience'),
        written_communication_strength=merged.get('written_communication_strength') or 'medium',
        self_assessed_strengths=merged.get('self_assessed_strengths') or [],
        self_assessed_gaps=[],
        skills=skills,
        unanswered_skills=unanswered_skills,
        resume_ids=[resume_id],
        onboarding_complete=False,
    )

    # --- Construct ResumeBaseline ---
    resume = ResumeBaseline(
        resume_id=resume_id,
        name=resume_data.get('name') or 'Resume',
        role_type=resume_data.get('role_type') or 'pm',
        profile_id=profile_id,
        work_experience=work_exp,
        skills=resume_data.get('skills') or [],
    )

    # --- Determine fields_requiring_followup ---
    followup: list[str] = list(ALWAYS_FOLLOWUP)

    # Add any inferrable required fields the LLM left null
    for field in INFERRABLE_REQUIRED:
        val = profile_data.get(field)
        if val is None and field not in followup:
            followup.append(field)

    # --- Parse quality ---
    quality = evaluate_parse_quality(profile, resume)
    if quality == 'low':
        warnings.append(
            'Sparse results from parse — if uploading PDF consider pasting as plain text '
            'for richer extraction.'
        )

    return profile, resume, quality, warnings, followup
