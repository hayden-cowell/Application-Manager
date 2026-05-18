import json
import os
from pathlib import Path
from typing import Optional
from schemas import FitAssessment

STORAGE_PATH = Path(os.getenv('STORAGE_PATH', 'data/assessments'))
STORAGE_PATH.mkdir(parents=True, exist_ok=True)


def save_assessment(a: FitAssessment) -> None:
    path = STORAGE_PATH / f'{a.assessment_id}.json'
    path.write_text(a.model_dump_json(indent=2), encoding='utf-8')


def get_assessment(assessment_id: str) -> Optional[FitAssessment]:
    path = STORAGE_PATH / f'{assessment_id}.json'
    if not path.exists():
        return None
    return FitAssessment.model_validate_json(path.read_text(encoding='utf-8'))


def list_assessments() -> list[FitAssessment]:
    results = []
    for f in STORAGE_PATH.glob('*.json'):
        try:
            results.append(FitAssessment.model_validate_json(f.read_text(encoding='utf-8')))
        except Exception:
            pass    # skip malformed files silently
    return sorted(results, key=lambda a: a.created_at, reverse=True)
