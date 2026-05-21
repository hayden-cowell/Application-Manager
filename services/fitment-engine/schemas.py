from pydantic import BaseModel, Field
from typing import Optional


class NotableLaunch(BaseModel):
    description: str
    impact: str


class Skill(BaseModel):
    name: str
    confirmed: bool    # True = has it, False = confirmed absent


class UserProfile(BaseModel):
    # NOTE: self_assessed_gaps must not duplicate skills already in confirmed_false
    # (i.e. skills with confirmed=False). Duplication causes self_assessed_gaps to override
    # the unanswered state of skills, collapsing unknown into absent and breaking the
    # three-state system for any skill mentioned in both places. Use self_assessed_gaps only
    # for nuanced gaps that don't map to a named skill (e.g. "executive storytelling",
    # "regulated industry experience"). The profile builder in Phase 2 should strip
    # self_assessed_gaps entries that duplicate confirmed_false skills.

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

    # Technical depth (structured supplements — populated when relevant skills are confirmed)
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
    largest_arr_supported_context: Optional[str] = None
    largest_dau_supported: Optional[int] = None
    cross_functional_scope: list[str] = []

    # Credentials and education
    highest_degree: Optional[str] = None
    degree_field: Optional[str] = None
    university_tier: Optional[str] = None
    certifications: list[str] = []

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
    presentation_experience: Optional[str] = None
    written_communication_strength: str   # 'low', 'medium', 'high'
    self_assessed_strengths: list[str] = []
    # Free-form weaknesses the candidate volunteers. Must not duplicate confirmed_false skills --
    # use only for nuanced gaps without a direct skill equivalent. See class-level note.
    self_assessed_gaps: list[str] = []

    # Skill list (replaces PM-specific boolean flags)
    # confirmed=True: has this skill; confirmed=False: confirmed absent
    skills: list[Skill] = []
    # Skills not yet collected (null / unknown state)
    unanswered_skills: list[str] = []

    # Metadata
    profile_id: str
    profile_version: int = 1
    onboarding_complete: bool = False


class JobPosting(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str                      # full text, no truncation
    source_url: Optional[str] = None
    import_source: Optional[str] = None   # 'linkedin', 'indeed', 'ziprecruiter', 'manual'
    imported_at: Optional[str] = None     # ISO timestamp


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
    action_tier: str                      # 'skip', 'apply_as_is', 'apply', 'light_tailoring', 'strong_fit'
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


class ScoreRequest(BaseModel):
    job: JobPosting
    profile: UserProfile
    resumes: list[ResumeBaseline]
    save_result: bool = True


class OverrideRequest(BaseModel):
    action: str     # 'applied_anyway', 'skipped_anyway'
    note: Optional[str] = None


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    estimated_cost_usd: float           # approximate; based on Haiku pricing at time of build


class AssessmentResponse(BaseModel):
    assessment: FitAssessment
    token_usage: TokenUsage
