import os
from pathlib import Path
from typing import Optional

# schemas resolves to services/fitment-engine/schemas.py via sys.path (set in main.py)
from schemas import UserProfile, ResumeBaseline  # type: ignore

PROFILES_PATH = Path(os.getenv('PROFILES_PATH', 'data/profiles'))
RESUMES_PATH  = Path(os.getenv('RESUMES_PATH',  'data/resumes'))
PROFILES_PATH.mkdir(parents=True, exist_ok=True)
RESUMES_PATH.mkdir(parents=True, exist_ok=True)


def save_profile(p: UserProfile) -> None:
    (PROFILES_PATH / f'{p.profile_id}.json').write_text(
        p.model_dump_json(indent=2), encoding='utf-8'
    )


def get_profile(profile_id: str) -> Optional[UserProfile]:
    path = PROFILES_PATH / f'{profile_id}.json'
    if not path.exists():
        return None
    return UserProfile.model_validate_json(path.read_text(encoding='utf-8'))


def save_resume(r: ResumeBaseline) -> None:
    (RESUMES_PATH / f'{r.resume_id}.json').write_text(
        r.model_dump_json(indent=2), encoding='utf-8'
    )


def get_resume(resume_id: str) -> Optional[ResumeBaseline]:
    path = RESUMES_PATH / f'{resume_id}.json'
    if not path.exists():
        return None
    return ResumeBaseline.model_validate_json(path.read_text(encoding='utf-8'))
