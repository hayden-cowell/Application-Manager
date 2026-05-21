"""
Usage:
  python test_runner.py                          # all profiles x all jobs
  python test_runner.py --profile profile_hayden_cowell
  python test_runner.py --job job_pm_workos
  python test_runner.py --profile profile_hayden_cowell --job job_pm_workos
"""
import argparse
import json
import httpx
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = 'http://localhost:8000'
EXPECTATIONS_PATH = Path('data/test_cases/jd_expectations.json')
RESULTS_DIR = Path('data/test_results')

PROFILE_RESUME_MAP = {
    'profile_hayden_cowell': 'resume_hayden_cowell_platform_pm',
    'profile_senior_pm': 'resume_platform_pm',
    'profile_midcareer_pm': 'resume_midcareer_pm_generalist',
    'profile_senior_tpm': 'resume_senior_tpm',
}


def load_expectations() -> dict:
    if EXPECTATIONS_PATH.exists():
        data = json.loads(EXPECTATIONS_PATH.read_text())
        return {j['job_id']: j for j in data.get('jobs', [])}
    return {}


def check_expectations(job_id: str, result: dict, expectations: dict) -> list[str]:
    """Returns list of violations found."""
    violations = []
    exp = expectations.get(job_id)
    if not exp:
        return violations

    eligibility = result.get('eligibility', {})
    passed = eligibility.get('passed', True)
    expected_elig = exp.get('expected_eligibility_for_us_remote_candidate')
    if expected_elig == 'fail' and passed:
        violations.append(f'EXPECTED eligibility=fail but got pass')
    if expected_elig == 'pass' and not passed:
        violations.append(f'EXPECTED eligibility=pass but got fail')

    expected_conf = exp.get('expected_confidence')
    actual_conf = result.get('confidence_level', '')
    if expected_conf == 'high' and actual_conf != 'high':
        violations.append(f'EXPECTED confidence=high but got {actual_conf}')
    if expected_conf == 'low' and actual_conf == 'high':
        violations.append(f'EXPECTED confidence<=medium but got high')

    must_not = exp.get('must_not_happen', [])
    if must_not:
        comp = result.get('competitiveness') or {}
        evid = result.get('evidence_strength') or {}
        search_text = ' '.join([
            result.get('reasoning_summary', ''),
            ' '.join(result.get('missing_signals', [])),
            ' '.join(result.get('tailoring_suggestions', [])),
            ' '.join(result.get('confidence_reasons', [])),
            result.get('action_tier', ''),
            result.get('confidence_level', ''),
            str(eligibility.get('passed', '')),
            ' '.join(comp.get('signals', [])),
            ' '.join(comp.get('gaps', [])),
            ' '.join(evid.get('signals', [])),
            ' '.join(evid.get('gaps', [])),
        ]).lower()
        for phrase in must_not:
            if phrase.lower() in search_text:
                violations.append(f'MUST_NOT_HAPPEN: "{phrase}"')

    return violations


def run(profile_filter: str | None, job_filter: str | None):
    profiles = {p.stem: json.loads(p.read_text()) for p in Path('data/profiles').glob('*.json')}
    jobs     = {j.stem: json.loads(j.read_text()) for j in Path('data/jobs').glob('*.json')}
    resumes  = {r.stem: json.loads(r.read_text()) for r in Path('data/resumes').glob('*.json')}
    expectations = load_expectations()

    if profile_filter:
        profiles = {k: v for k, v in profiles.items() if profile_filter in k}
    if job_filter:
        jobs = {k: v for k, v in jobs.items() if job_filter in k}

    print(f'Running {len(profiles)} profile(s) x {len(jobs)} job(s)')
    print('=' * 80)

    all_results = []
    totals = dict(input=0, output=0, cache_w=0, cache_r=0, cost=0.0, calls=0)

    for job_id, job in sorted(jobs.items()):
        for profile_id, profile in sorted(profiles.items()):
            label = f'{profile_id} x {job_id}'
            print(f'\n--- {label} ---')
            try:
                resume_id = PROFILE_RESUME_MAP.get(profile_id)
                resumes_for_profile = (
                    [resumes[resume_id]] if resume_id and resume_id in resumes
                    else list(resumes.values())
                )
                resp = httpx.post(f'{BASE_URL}/assess', json={
                    'job': job,
                    'profile': profile,
                    'resumes': resumes_for_profile,
                    'save_result': True
                }, timeout=60)
                resp.raise_for_status()
                data   = resp.json()
                result = data['assessment']
                usage  = data['token_usage']

                score   = result['score']
                tier    = result['action_tier']
                conf    = result['confidence_level']
                summary = result['reasoning_summary']
                gaps    = result.get('missing_signals', [])

                in_tok  = usage['input_tokens']
                out_tok = usage['output_tokens']
                c_write = usage['cache_creation_input_tokens']
                c_read  = usage['cache_read_input_tokens']
                cost    = usage['estimated_cost_usd']

                violations = check_expectations(job_id, result, expectations)

                print(f'Score: {score}  Tier: {tier}  Confidence: {conf}')
                print(f'Summary: {summary}')
                if gaps:
                    print(f'Missing signals: {gaps}')
                cache_note = ''
                if c_write:
                    cache_note += f'  cache_write={c_write}'
                if c_read:
                    cache_note += f'  cache_read={c_read}'
                print(f'Tokens: in={in_tok}  out={out_tok}{cache_note}  est=${cost:.5f}')
                for v in violations:
                    print(f'  [VIOLATION] {v}')

                totals['input']   += in_tok
                totals['output']  += out_tok
                totals['cache_w'] += c_write
                totals['cache_r'] += c_read
                totals['cost']    += cost
                totals['calls']   += 1

                all_results.append({
                    'profile_id': profile_id,
                    'job_id': job_id,
                    'score': score,
                    'action_tier': tier,
                    'confidence_level': conf,
                    'eligibility_passed': result.get('eligibility', {}).get('passed'),
                    'reasoning_summary': summary,
                    'missing_signals': gaps,
                    'competitiveness_score': (result.get('competitiveness') or {}).get('score'),
                    'evidence_score': (result.get('evidence_strength') or {}).get('score'),
                    'input_tokens': in_tok,
                    'output_tokens': out_tok,
                    'cache_creation_input_tokens': c_write,
                    'cache_read_input_tokens': c_read,
                    'estimated_cost_usd': cost,
                    'expectation_violations': violations,
                })

            except httpx.HTTPStatusError as e:
                print(f'HTTP ERROR {e.response.status_code}: {e.response.text}')
                all_results.append({'profile_id': profile_id, 'job_id': job_id, 'error': str(e)})
            except Exception as e:
                print(f'ERROR: {e}')
                all_results.append({'profile_id': profile_id, 'job_id': job_id, 'error': str(e)})

    n = totals['calls']
    if n:
        print(f'\n{"=" * 80}')
        print(f'RESULTS TABLE')
        print(f'{"=" * 80}')
        header = f'{"Job ID":<35} {"Score":>5} {"Tier":<18} {"Conf":<8} {"In":>6} {"CW":>6} {"CR":>6} {"Out":>6} {"Cost":>9}'
        print(header)
        print('-' * len(header))
        for r in all_results:
            if 'error' in r:
                print(f'{r["job_id"]:<35} ERROR: {r["error"]}')
                continue
            cw = r['cache_creation_input_tokens']
            cr = r['cache_read_input_tokens']
            print(
                f'{r["job_id"]:<35} {r["score"]:>5} {r["action_tier"]:<18} '
                f'{r["confidence_level"]:<8} {r["input_tokens"]:>6} {cw:>6} {cr:>6} '
                f'{r["output_tokens"]:>6} ${r["estimated_cost_usd"]:>8.5f}'
            )

        violations_found = [r for r in all_results if r.get('expectation_violations')]
        if violations_found:
            print(f'\nEXPECTATION VIOLATIONS ({len(violations_found)} jobs):')
            for r in violations_found:
                for v in r['expectation_violations']:
                    print(f'  {r["job_id"]}: {v}')

        print(f'\n{"=" * 80}')
        print(f'TOTALS ({n} calls)')
        print(f'  Input tokens:    {totals["input"]:,}')
        print(f'  Output tokens:   {totals["output"]:,}')
        if totals['cache_w']:
            print(f'  Cache writes:    {totals["cache_w"]:,}')
        if totals['cache_r']:
            print(f'  Cache reads:     {totals["cache_r"]:,}')
        print(f'  Estimated total: ${totals["cost"]:.5f}')
        print(f'  Avg per call:    ${totals["cost"] / n:.5f}')

    _save_results(all_results, profile_filter, job_filter)


def _save_results(results: list[dict], profile_filter, job_filter):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    tag = ''
    if profile_filter:
        tag += f'_{profile_filter}'
    if job_filter:
        tag += f'_{job_filter}'
    path = RESULTS_DIR / f'run_{ts}{tag}.json'
    path.write_text(json.dumps({
        'run_at': datetime.now(timezone.utc).isoformat(),
        'profile_filter': profile_filter,
        'job_filter': job_filter,
        'results': results,
    }, indent=2))
    print(f'\nResults saved to {path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', help='Filter by profile_id substring')
    parser.add_argument('--job', help='Filter by job_id substring')
    args = parser.parse_args()
    run(args.profile, args.job)
