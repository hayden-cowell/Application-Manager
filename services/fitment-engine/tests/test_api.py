import json
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key')

# Use a temp directory for storage during tests
_tmp_storage = tempfile.mkdtemp()
os.environ['STORAGE_PATH'] = _tmp_storage

from fastapi.testclient import TestClient
from main import app
from schemas import FitAssessment, EligibilityGate

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_storage():
    for f in Path(_tmp_storage).glob('*.json'):
        f.unlink()
    yield
    for f in Path(_tmp_storage).glob('*.json'):
        f.unlink()


def _make_request_payload():
    with open('data/profiles/profile_senior_pm.json') as f:
        profile = json.load(f)
    with open('data/jobs/job_strong_fit.json') as f:
        job = json.load(f)
    with open('data/resumes/resume_platform_pm.json') as f:
        resume = json.load(f)
    return {'job': job, 'profile': profile, 'resumes': [resume], 'save_result': False}


def _mock_assessment():
    return FitAssessment(
        assessment_id='test-uuid-1234',
        job_id='job_strong_fit',
        profile_id='profile_senior_pm',
        prompt_version='1.0',
        created_at='2026-05-18T10:00:00+00:00',
        eligibility=EligibilityGate(passed=True, reasons=[]),
        score=88,
        action_tier='light_tailoring',
        reasoning_summary='Strong fit for this platform PM role.',
        missing_signals=[],
        tailoring_suggestions=['Emphasize API experience'],
        confidence_level='high',
        confidence_reasons=['Complete profile and detailed JD'],
    )


# ── /health ────────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get('/health')
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'ok'
    assert data['prompt_version'] == '1.0'


# ── /assess ────────────────────────────────────────────────────────────────────

def test_assess_returns_assessment():
    payload = _make_request_payload()
    with patch('main.score_job', return_value=_mock_assessment()):
        resp = client.post('/assess', json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data['score'] == 88
    assert data['action_tier'] == 'light_tailoring'
    assert data['profile_id'] == 'profile_senior_pm'


def test_assess_returns_500_on_llm_failure():
    payload = _make_request_payload()
    with patch('main.score_job', side_effect=Exception('LLM call failed: unexpected token')):
        resp = client.post('/assess', json=payload)
    assert resp.status_code == 500
    assert 'LLM call failed' in resp.json()['detail']


def test_assess_saves_result_when_requested():
    payload = _make_request_payload()
    payload['save_result'] = True
    mock_result = _mock_assessment()
    with patch('main.score_job', return_value=mock_result):
        resp = client.post('/assess', json=payload)
    assert resp.status_code == 200
    saved = list(Path(_tmp_storage).glob('*.json'))
    assert len(saved) == 1


def test_assess_does_not_save_when_not_requested():
    payload = _make_request_payload()
    payload['save_result'] = False
    with patch('main.score_job', return_value=_mock_assessment()):
        resp = client.post('/assess', json=payload)
    assert resp.status_code == 200
    saved = list(Path(_tmp_storage).glob('*.json'))
    assert len(saved) == 0


# ── /assessments ───────────────────────────────────────────────────────────────

def test_list_assessments_empty():
    resp = client.get('/assessments')
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_assessments_returns_saved():
    payload = _make_request_payload()
    payload['save_result'] = True
    with patch('main.score_job', return_value=_mock_assessment()):
        client.post('/assess', json=payload)
    resp = client.get('/assessments')
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── /assessments/{id} ─────────────────────────────────────────────────────────

def test_get_assessment_not_found():
    resp = client.get('/assessments/nonexistent-id')
    assert resp.status_code == 404


def test_get_assessment_found():
    payload = _make_request_payload()
    payload['save_result'] = True
    mock = _mock_assessment()
    with patch('main.score_job', return_value=mock):
        client.post('/assess', json=payload)
    resp = client.get(f'/assessments/{mock.assessment_id}')
    assert resp.status_code == 200
    assert resp.json()['assessment_id'] == mock.assessment_id


# ── /assessments/{id}/override ────────────────────────────────────────────────

def test_override_not_found():
    resp = client.post('/assessments/bad-id/override', json={'action': 'applied_anyway'})
    assert resp.status_code == 404


def test_override_logs_action():
    payload = _make_request_payload()
    payload['save_result'] = True
    mock = _mock_assessment()
    with patch('main.score_job', return_value=mock):
        client.post('/assess', json=payload)
    resp = client.post(
        f'/assessments/{mock.assessment_id}/override',
        json={'action': 'applied_anyway', 'note': 'Worth trying'}
    )
    assert resp.status_code == 200
    assert resp.json()['status'] == 'logged'

    updated = client.get(f'/assessments/{mock.assessment_id}').json()
    assert updated['user_overridden'] is True
    assert updated['override_action'] == 'applied_anyway'
