"""
Usage: python test_runner.py
Runs all profile x job combinations and prints assessment results with token usage.
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

    total_input   = 0
    total_output  = 0
    total_cache_w = 0
    total_cache_r = 0
    total_cost    = 0.0
    call_count    = 0

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
                data   = resp.json()
                result = data['assessment']
                usage  = data['token_usage']

                print(f'Score: {result["score"]}  Tier: {result["action_tier"]}')
                print(f'Confidence: {result["confidence_level"]}')
                print(f'Summary: {result["reasoning_summary"]}')
                if result['missing_signals']:
                    print(f'Gaps: {result["missing_signals"]}')

                in_tok  = usage['input_tokens']
                out_tok = usage['output_tokens']
                c_write = usage['cache_creation_input_tokens']
                c_read  = usage['cache_read_input_tokens']
                cost    = usage['estimated_cost_usd']
                cache_note = ''
                if c_write:
                    cache_note += f'  cache_write={c_write}'
                if c_read:
                    cache_note += f'  cache_read={c_read}'
                print(f'Tokens: in={in_tok}  out={out_tok}{cache_note}  est=${cost:.5f}')

                total_input   += in_tok
                total_output  += out_tok
                total_cache_w += c_write
                total_cache_r += c_read
                total_cost    += cost
                call_count    += 1

            except httpx.HTTPStatusError as e:
                print(f'ERROR {e.response.status_code}: {e.response.text}')
            except Exception as e:
                print(f'ERROR: {e}')

    if call_count:
        print(f'\n{"=" * 60}')
        print(f'TOTAL ({call_count} calls)')
        print(f'  Input tokens:        {total_input:,}')
        print(f'  Output tokens:       {total_output:,}')
        if total_cache_w:
            print(f'  Cache writes:        {total_cache_w:,}')
        if total_cache_r:
            print(f'  Cache reads:         {total_cache_r:,}')
        print(f'  Avg input/call:      {total_input // call_count:,}')
        print(f'  Avg output/call:     {total_output // call_count:,}')
        print(f'  Estimated total:     ${total_cost:.5f}')
        print(f'  Estimated per call:  ${total_cost / call_count:.5f}')


def load_all(directory: str) -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in Path(directory).glob('*.json')
    ]


if __name__ == '__main__':
    run_all()
