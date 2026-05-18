"""
Usage: python test_runner.py
Runs all profile x job combinations and prints assessment results.
"""
import json
import httpx
from pathlib import Path

BASE_URL = 'http://localhost:8000'


def run_all():
    profiles = load_all('data/profiles')
    jobs     = load_all('data/jobs')
    resumes  = load_all('data/resumes')

    print(f'Loaded {len(profiles)} profiles, {len(jobs)} jobs, {len(resumes)} resumes')
    print('=' * 60)

    for job in jobs:
        for profile in profiles:
            print(f'\n--- {profile["profile_id"]} x {job["job_id"]} ---')
            try:
                resp = httpx.post(f'{BASE_URL}/assess', json={
                    'job': job,
                    'profile': profile,
                    'resumes': resumes,
                    'save_result': True
                }, timeout=30)
                resp.raise_for_status()
                result = resp.json()
                print(f'Score: {result["score"]}  Tier: {result["action_tier"]}')
                print(f'Confidence: {result["confidence_level"]}')
                print(f'Summary: {result["reasoning_summary"]}')
                if result['missing_signals']:
                    print(f'Gaps: {result["missing_signals"]}')
            except httpx.HTTPStatusError as e:
                print(f'ERROR {e.response.status_code}: {e.response.text}')
            except Exception as e:
                print(f'ERROR: {e}')


def load_all(directory: str) -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in Path(directory).glob('*.json')
    ]


if __name__ == '__main__':
    run_all()
