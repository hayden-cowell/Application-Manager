"""
Ablation test harness for the fitment engine.

Usage:
  python ablation_runner.py                  # all categories
  python ablation_runner.py --category 2     # category 2 only (three-state validation)
  python ablation_runner.py --category 1     # sparse vs. full profile
  python ablation_runner.py --category 3     # cross-profile ranking
"""
import os
from pathlib import Path


def _load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()  # must run before scorer import — client initialises at import time

import argparse
import json
from datetime import datetime, timezone

from scorer import score_job
from schemas import ScoreRequest, UserProfile, JobPosting, ResumeBaseline, Skill

RESULTS_DIR = Path('data/ablation_results')

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_jobs() -> dict[str, JobPosting]:
    return {j.stem: JobPosting(**json.loads(j.read_text())) for j in Path('data/jobs').glob('*.json')}


def load_profiles() -> dict[str, UserProfile]:
    result = {}
    for p in Path('data/profiles').glob('*.json'):
        profile = UserProfile(**json.loads(p.read_text()))
        result[profile.profile_id] = profile
    return result


def load_resumes() -> dict[str, ResumeBaseline]:
    return {r.stem: ResumeBaseline(**json.loads(r.read_text())) for r in Path('data/resumes').glob('*.json')}


# ---------------------------------------------------------------------------
# Sparse profile builder (Category 1)
# ---------------------------------------------------------------------------

_OPTIONAL_SCALAR_FIELDS = [
    'largest_arr_supported', 'largest_arr_supported_context', 'largest_dau_supported',
    'largest_company_size', 'smallest_company_size', 'technical_background',
    'stakeholder_management_level', 'presentation_experience',
    'highest_degree', 'degree_field', 'university_tier',
]

_LIST_FIELDS_TO_CLEAR = [
    'notable_launches', 'self_assessed_gaps', 'self_assessed_strengths',
    'coding_languages', 'data_tools', 'cross_functional_scope',
    'communication_artifacts', 'certifications', 'product_areas',
]


def build_sparse_profile(full: UserProfile) -> UserProfile:
    d = full.model_dump()
    d['profile_id'] = 'profile_hayden_sparse'
    # Move all skills to unanswered — simulates a day-one user with no flags answered
    all_skill_names = [s['name'] for s in d.get('skills', [])]
    d['skills'] = []
    d['unanswered_skills'] = all_skill_names + list(d.get('unanswered_skills', []))
    for f in _OPTIONAL_SCALAR_FIELDS:
        d[f] = None
    for f in _LIST_FIELDS_TO_CLEAR:
        d[f] = []
    return UserProfile(**d)


# ---------------------------------------------------------------------------
# Score wrapper
# ---------------------------------------------------------------------------

def run_score(job: JobPosting, profile: UserProfile, resumes: list[ResumeBaseline]) -> dict:
    request = ScoreRequest(job=job, profile=profile, resumes=resumes, save_result=False)
    assessment, usage = score_job(request)
    gate_fired = not assessment.eligibility.passed
    comp = assessment.competitiveness
    evid = assessment.evidence_strength
    return {
        'job_id': job.job_id,
        'profile_id': profile.profile_id,
        'gate_fired': gate_fired,
        'score': assessment.score,
        'action_tier': assessment.action_tier,
        'confidence_level': assessment.confidence_level,
        'reasoning_summary': assessment.reasoning_summary,
        'missing_signals': assessment.missing_signals,
        'gate_reasons': assessment.eligibility.reasons if gate_fired else [],
        'competitiveness_score': comp.score if comp else None,
        'evidence_score': evid.score if evid else None,
        'usage': usage.model_dump(),
    }


def _add_usage(totals: dict, r: dict):
    if not r['gate_fired']:
        u = r['usage']
        totals['input']   += u['input_tokens']
        totals['output']  += u['output_tokens']
        totals['cache_w'] += u['cache_creation_input_tokens']
        totals['cache_r'] += u['cache_read_input_tokens']
        totals['cost']    += u['estimated_cost_usd']
        totals['calls']   += 1
    else:
        totals['gate_failures'] += 1


def _blank_totals() -> dict:
    return dict(input=0, output=0, cache_w=0, cache_r=0, cost=0.0, calls=0, gate_failures=0)


def _print_totals(totals: dict, label: str):
    n = totals['calls']
    g = totals['gate_failures']
    print(f'\n{label}: {n} LLM calls, {g} gate failures, est. ${totals["cost"]:.4f}')


# ---------------------------------------------------------------------------
# Resume mapping
# ---------------------------------------------------------------------------

def get_resume_for_profile(
    profile: UserProfile,
    resumes: dict[str, ResumeBaseline]
) -> ResumeBaseline:
    if not profile.resume_ids:
        raise ValueError(
            f"Profile {profile.profile_id} has no resume_ids. "
            f"Link a resume before running ablation tests."
        )
    for resume_id in profile.resume_ids:
        if resume_id in resumes:
            return resumes[resume_id]
    raise ValueError(
        f"Profile {profile.profile_id} lists resume_ids {profile.resume_ids} "
        f"but none were found in the loaded resumes. "
        f"Ensure the resume file exists in data/resumes/."
    )


# ---------------------------------------------------------------------------
# Category 1: Sparse vs. full
# ---------------------------------------------------------------------------

def run_category_1(jobs: dict, profiles: dict, resumes: dict) -> dict:
    print('\n' + '=' * 80)
    print('CATEGORY 1: SPARSE vs. FULL PROFILE')
    print('  Measures how much structured flags contribute beyond resume text alone.')
    print('=' * 80)

    full_profile  = profiles['profile_hayden_cowell']
    sparse_profile = build_sparse_profile(full_profile)
    hayden_resume  = [get_resume_for_profile(full_profile, resumes)]
    totals  = _blank_totals()
    results = []

    header = f'{"Job":<40} {"Full":>5} {"Sparse":>6} {"Delta":>6}  {"Full Conf":<10} {"Sparse Conf":<12} {"Tier Chg"}'
    print(f'\n{header}')
    print('-' * len(header))

    for job_id, job in sorted(jobs.items()):
        full_r   = run_score(job, full_profile, hayden_resume)
        sparse_r = run_score(job, sparse_profile, hayden_resume)
        _add_usage(totals, full_r)
        _add_usage(totals, sparse_r)

        full_score   = full_r['score']
        sparse_score = sparse_r['score']
        full_gate    = full_r['gate_fired']
        sparse_gate  = sparse_r['gate_fired']
        tier_changed = full_r['action_tier'] != sparse_r['action_tier']

        delta      = (full_score - sparse_score) if not (full_gate or sparse_gate) else None
        delta_str  = f'{delta:+d}' if delta is not None else 'n/a'
        tier_str   = 'YES' if tier_changed else 'no'
        gate_note  = (' [GATE:full]' if full_gate else '') + (' [GATE:sparse]' if sparse_gate else '')
        bug_flag   = '  *** BUG: sparse > full ***' if (delta is not None and delta < 0) else ''

        print(
            f'{job_id:<40} {full_score:>5} {sparse_score:>6} {delta_str:>6}  '
            f'{full_r["confidence_level"]:<10} {sparse_r["confidence_level"]:<12} '
            f'{tier_str}{gate_note}{bug_flag}'
        )

        results.append({
            'job_id': job_id, 'full': full_r, 'sparse': sparse_r,
            'delta': delta, 'tier_changed': tier_changed,
        })

    valid = [r for r in results if r['delta'] is not None]
    bugs  = [r for r in valid if r['delta'] < 0]

    print(f'\nSUMMARY — Category 1')
    if valid:
        by_delta = sorted(valid, key=lambda r: abs(r['delta']), reverse=True)
        print('  Largest deltas (|full - sparse|):')
        for r in by_delta[:5]:
            print(f'    {r["job_id"]}: {r["delta"]:+d}')
        avg = sum(r['delta'] for r in valid) / len(valid)
        print(f'  Average delta: {avg:+.1f}')
    if bugs:
        print(f'  *** BUGS — sparse scored HIGHER than full on {len(bugs)} job(s): ***')
        for r in bugs:
            print(f'    {r["job_id"]}: sparse={r["sparse"]["score"]} > full={r["full"]["score"]}')
    else:
        print('  No cases where sparse > full. ✓')

    _print_totals(totals, 'Category 1 totals')
    return {'results': results, 'totals': totals}


# ---------------------------------------------------------------------------
# Category 2: Flag ablation
# ---------------------------------------------------------------------------

STANDARD_FLAGS = {
    'growth experimentation':      ['job_borderline', 'job_gap_match', 'job_pm_workos', 'job_pm_edmunds_adtech'],
    'pricing and packaging':       ['job_borderline', 'job_gap_match', 'job_sr_pm_autodesk_access'],
    '0 to 1 product development':  ['job_pm_workos', 'job_lead_pm_panorama_platform', 'job_strong_fit'],
    'platform product management': ['job_strong_fit', 'job_lead_pm_panorama_platform', 'job_tpm_cloud_platform'],
}


def _set_skill(profile: UserProfile, skill_name: str, val) -> UserProfile:
    skills_without     = [s for s in profile.skills if s.name != skill_name]
    unanswered_without = [n for n in profile.unanswered_skills if n != skill_name]
    if val is True:
        return profile.model_copy(update={
            'skills': skills_without + [Skill(name=skill_name, confirmed=True)],
            'unanswered_skills': unanswered_without,
        })
    elif val is False:
        return profile.model_copy(update={
            'skills': skills_without + [Skill(name=skill_name, confirmed=False)],
            'unanswered_skills': unanswered_without,
        })
    else:  # None
        return profile.model_copy(update={
            'skills': skills_without,
            'unanswered_skills': unanswered_without + [skill_name],
        })

_ARR_VARIANTS = [
    ('$800M+ (platform supporting ZoomInfo core data products)', 'platform_pm_not_direct_owner', '$800M+_ctx'),
    ('$40M', None, '$40M_no_ctx'),
    (None, None, 'null'),
]

_SELF_GAP_VARIANTS = [
    (['pricing and packaging', 'product-led growth', 'consumer products'], 'full_gaps'),
    ([], 'empty_gaps'),
]

_ARR_JOBS = ['job_borderline', 'job_sr_pm_autodesk_access', 'job_lead_pm_panorama_platform']
_GAP_JOBS = ['job_borderline', 'job_gap_match', 'job_pm_workos']


def run_category_2(jobs: dict, profiles: dict, resumes: dict) -> dict:
    print('\n' + '=' * 80)
    print('CATEGORY 2: FLAG ABLATION')
    print('  Key test: F-N delta (false minus null). If consistently 0, null is being')
    print('  treated as false — the three-state system is not working.')
    print('=' * 80)
    print('NOTE: self_assessed_gaps cleared in all Category 2 variants to isolate flag')
    print('      signal from self_assessed_gaps overlap. Production behavior differs when')
    print('      both signals are present. See ablation findings for details.')

    base   = profiles['profile_hayden_cowell']
    resume = [get_resume_for_profile(base, resumes)]
    totals = _blank_totals()
    all_flag_results: dict = {}
    fn_deltas_by_flag: dict[str, list] = {}

    # ---- Standard three-state flags ----
    for skill_name, job_ids in STANDARD_FLAGS.items():
        print(f'\n--- Skill: {skill_name} ---')
        header = (
            f'{"Job":<40} {"True":>5} {"False":>5} {"Null":>5} '
            f'{"T-F":>5} {"F-N":>5}  {"Conf T/F/N":<22} {"Tier T/F/N"}'
        )
        print(header)
        print('-' * len(header))

        flag_results = []
        fn_deltas_by_flag[skill_name] = []

        for job_id in job_ids:
            if job_id not in jobs:
                print(f'  {job_id}: NOT FOUND — skip')
                continue
            job = jobs[job_id]

            row: dict[str, dict] = {}
            for val in (True, False, None):
                variant = _set_skill(base, skill_name, val).model_copy(update={
                    'self_assessed_gaps': [],  # isolate skill signal from self_assessed overlap
                })
                r = run_score(job, variant, resume)
                _add_usage(totals, r)
                label = 'true' if val is True else ('false' if val is False else 'null')
                row[label] = r

            t, f_, n = row['true'], row['false'], row['null']
            tg, fg, ng = t['gate_fired'], f_['gate_fired'], n['gate_fired']

            tf_delta = (t['score'] - f_['score']) if not (tg or fg) else None
            fn_delta = (f_['score'] - n['score']) if not (fg or ng) else None
            fn_deltas_by_flag[skill_name].append(fn_delta)

            tf_str  = f'{tf_delta:+d}' if tf_delta is not None else 'n/a'
            fn_mark = '!' if (fn_delta == 0) else ('?' if (fn_delta is not None and fn_delta < 0) else ' ')
            fn_str  = (f'{fn_delta:+d}' if fn_delta is not None else 'n/a') + fn_mark

            conf_str = f'{t["confidence_level"]}/{f_["confidence_level"]}/{n["confidence_level"]}'
            tier_str = f'{t["action_tier"]}/{f_["action_tier"]}/{n["action_tier"]}'
            gate_str = (''.join(
                lbl for lbl, fired in [('[Gt]', tg), ('[Gf]', fg), ('[Gn]', ng)] if fired
            ))

            print(
                f'{job_id:<40} {t["score"]:>5} {f_["score"]:>5} {n["score"]:>5} '
                f'{tf_str:>5} {fn_str:<6}  {conf_str:<22} {tier_str}{gate_str}'
            )

            flag_results.append({
                'job_id': job_id, 'true': t, 'false': f_, 'null': n,
                'tf_delta': tf_delta, 'fn_delta': fn_delta,
            })

        all_flag_results[skill_name] = flag_results

    # ---- largest_arr_supported ----
    print(f'\n--- Field: largest_arr_supported ---')
    arr_results = []
    header_arr = f'{"Job":<40} {"$800M+":>8} {"$40M":>8} {"null":>8}  {"Δ 800-40":>9} {"Δ 40-null":>10}'
    print(header_arr)
    print('-' * len(header_arr))
    for job_id in _ARR_JOBS:
        if job_id not in jobs:
            print(f'  {job_id}: NOT FOUND — skip')
            continue
        job = jobs[job_id]
        row_arr: dict[str, dict] = {}
        for arr_val, ctx_val, label in _ARR_VARIANTS:
            variant = base.model_copy(update={
                'largest_arr_supported': arr_val,
                'largest_arr_supported_context': ctx_val,
            })
            r = run_score(job, variant, resume)
            _add_usage(totals, r)
            row_arr[label] = r
        s1 = row_arr['$800M+_ctx']['score']
        s2 = row_arr['$40M_no_ctx']['score']
        s3 = row_arr['null']['score']
        d1, d2 = s1 - s2, s2 - s3
        print(f'{job_id:<40} {s1:>8} {s2:>8} {s3:>8}  {d1:>+9} {d2:>+10}')
        arr_results.append({
            'job_id': job_id,
            '$800M+_ctx': row_arr['$800M+_ctx'],
            '$40M_no_ctx': row_arr['$40M_no_ctx'],
            'null': row_arr['null'],
            'delta_800_40': d1,
            'delta_40_null': d2,
        })
    all_flag_results['largest_arr_supported'] = arr_results

    # ---- self_assessed_gaps ----
    print(f'\n--- Field: self_assessed_gaps (full vs. empty — no null state for lists) ---')
    gap_results = []
    header_gap = f'{"Job":<40} {"Full":>5} {"Empty":>6} {"Delta":>6}  {"Conf F/E":<16} {"Tier F/E"}'
    print(header_gap)
    print('-' * len(header_gap))
    for job_id in _GAP_JOBS:
        if job_id not in jobs:
            print(f'  {job_id}: NOT FOUND — skip')
            continue
        job = jobs[job_id]
        row_gap: dict[str, dict] = {}
        for gaps_val, label in _SELF_GAP_VARIANTS:
            variant = base.model_copy(update={'self_assessed_gaps': gaps_val})
            r = run_score(job, variant, resume)
            _add_usage(totals, r)
            row_gap[label] = r
        s_full  = row_gap['full_gaps']['score']
        s_empty = row_gap['empty_gaps']['score']
        delta   = s_full - s_empty
        conf_str = f'{row_gap["full_gaps"]["confidence_level"]}/{row_gap["empty_gaps"]["confidence_level"]}'
        tier_str = f'{row_gap["full_gaps"]["action_tier"]}/{row_gap["empty_gaps"]["action_tier"]}'
        print(f'{job_id:<40} {s_full:>5} {s_empty:>6} {delta:>+6}  {conf_str:<16} {tier_str}')
        gap_results.append({
            'job_id': job_id, 'full_gaps': row_gap['full_gaps'],
            'empty_gaps': row_gap['empty_gaps'], 'delta': delta,
        })
    all_flag_results['self_assessed_gaps'] = gap_results

    # ---- THREE-STATE VALIDATION SUMMARY ----
    print('\n')
    print('═' * 62)
    print('THREE-STATE VALIDATION SUMMARY')
    print('  ! = F-N delta 0 (null treated same as false)')
    print('  ? = null scored HIGHER than false (unexpected)')
    print('═' * 62)

    hdr = f'{"Flag":<35} {"F-N pairs":>10} {"Zero Δ":>8}   {"Verdict"}'
    print(hdr)
    print('-' * len(hdr))

    warnings, partials = [], []
    for skill_name, deltas in fn_deltas_by_flag.items():
        valid_d = [d for d in deltas if d is not None]
        zero_count = sum(1 for d in valid_d if d == 0)
        n = len(valid_d)
        if n == 0:
            verdict = 'no data'
        elif zero_count == n:
            verdict = 'WARNING ⚠'
            warnings.append(skill_name)
        elif zero_count > 0:
            verdict = f'Partial ({zero_count}/{n} zero)'
            partials.append(skill_name)
        else:
            verdict = 'OK ✓'
        print(f'{skill_name:<35} {n:>10} {zero_count:>8}   {verdict}')

    print()
    if warnings:
        print(f'⚠  WARNING: {", ".join(warnings)}')
        print('   F-N delta = 0 on ALL tested jobs for these flags.')
        print('   Null is being treated identically to false.')
        print('   The three-state system is NOT working for these fields.')
        print('   The model is penalizing unknown values as if they were confirmed gaps.')
    elif partials:
        print(f'   Note: Some F-N zeros on {", ".join(partials)} — investigate those specific jobs.')
    else:
        print('   Three-state system appears to be working correctly for all tested flags. ✓')
    print('═' * 62)

    _print_totals(totals, 'Category 2 totals')
    return {'flags': all_flag_results, 'totals': totals}


# ---------------------------------------------------------------------------
# Category 3: Cross-profile comparison
# ---------------------------------------------------------------------------

CATEGORY_3_PROFILES = ['profile_hayden_cowell', 'profile_senior_pm', 'profile_midcareer_pm', 'profile_senior_tpm']
CATEGORY_3_JOBS     = ['job_strong_fit', 'job_lead_pm_panorama_platform', 'job_pm_workos', 'job_borderline', 'job_gap_match']

EXPECTED_RANKINGS: dict[str, list[str]] = {
    'job_strong_fit': [
        'profile_senior_pm',
        'profile_senior_tpm',
        'profile_hayden_cowell',
        'profile_midcareer_pm',
    ],
    'job_lead_pm_panorama_platform': [
        'profile_hayden_cowell',   # OR profile_senior_pm acceptable
        'profile_senior_pm',
        'profile_senior_tpm',
        'profile_midcareer_pm',
    ],
    'job_pm_workos': [
        'profile_senior_pm',
        'profile_hayden_cowell',
        'profile_senior_tpm',
        'profile_midcareer_pm',
    ],
}

# Pairs where either order is acceptable
_FLEXIBLE_PAIRS: dict[str, set] = {
    'job_lead_pm_panorama_platform': {frozenset(['profile_hayden_cowell', 'profile_senior_pm'])},
}


def _check_ranking_violations(job_id: str, actual_order: list[str]) -> list[str]:
    expected = EXPECTED_RANKINGS.get(job_id)
    if not expected:
        return []
    flexible = _FLEXIBLE_PAIRS.get(job_id, set())
    violations = []
    for i in range(len(actual_order)):
        for j in range(i + 1, len(actual_order)):
            higher = actual_order[i]   # scored higher in actual
            lower  = actual_order[j]   # scored lower in actual
            if higher not in expected or lower not in expected:
                continue
            if frozenset([higher, lower]) in flexible:
                continue
            if expected.index(higher) > expected.index(lower):
                violations.append(
                    f'{higher} scored higher than {lower}, but {lower} should rank above {higher}'
                )
    return violations


def run_category_3(jobs: dict, profiles: dict, resumes: dict) -> dict:
    print('\n' + '=' * 80)
    print('CATEGORY 3: CROSS-PROFILE COMPARISON')
    print('  Validates that scores rank candidates correctly relative to each other.')
    print('=' * 80)

    totals         = _blank_totals()
    all_results    = []
    all_violations = []

    for job_id in CATEGORY_3_JOBS:
        if job_id not in jobs:
            print(f'\n  {job_id}: NOT FOUND — skip')
            continue
        job = jobs[job_id]
        print(f'\nJob: {job_id}')
        header = f'  {"Profile":<30} {"Score":>5} {"Tier":<18} {"Conf":<8} {"Top Gap"}'
        print(header)
        print('  ' + '-' * (len(header) - 2))

        job_rows = []
        for pid in CATEGORY_3_PROFILES:
            if pid not in profiles:
                print(f'  {pid}: NOT FOUND — skip')
                continue
            try:
                resume = get_resume_for_profile(profiles[pid], resumes)
            except ValueError as e:
                print(f'  {pid}: {e} — skip')
                continue
            r = run_score(job, profiles[pid], [resume])
            _add_usage(totals, r)
            job_rows.append(r)

        job_rows.sort(key=lambda x: x['score'], reverse=True)
        actual_order = [r['profile_id'] for r in job_rows]

        for r in job_rows:
            top_gap  = (r['missing_signals'][0][:50] if r['missing_signals'] else '—')
            gate_str = ' [GATE]' if r['gate_fired'] else ''
            print(f'  {r["profile_id"]:<30} {r["score"]:>5} {r["action_tier"]:<18} {r["confidence_level"]:<8} "{top_gap}"{gate_str}')

        violations = _check_ranking_violations(job_id, actual_order)
        for v in violations:
            print(f'  RANKING VIOLATION: {v}')
        all_violations.extend([(job_id, v) for v in violations])
        all_results.append({'job_id': job_id, 'rows': job_rows, 'violations': violations})

    print(f'\nSUMMARY — Category 3')
    print(f'  Total ranking violations: {len(all_violations)}')
    if all_violations:
        for job_id, v in all_violations:
            print(f'    [{job_id}] {v}')
    else:
        print('  All ranking expectations met. ✓')

    _print_totals(totals, 'Category 3 totals')
    return {'results': all_results, 'totals': totals}


# ---------------------------------------------------------------------------
# Cost estimate + confirmation
# ---------------------------------------------------------------------------

_CAT_ESTIMATES = {
    1: (30, '15 jobs × 2 profiles (sparse + full)'),
    2: (54, '~54 flag variants across 4 flags + special fields'),
    3: (20, '5 jobs × 4 profiles'),
}
_COST_PER_CALL = 0.019


def print_cost_estimate(categories: list[int]) -> bool:
    print('\nABLATION TEST RUNNER')
    print('=' * 52)
    total_calls = 0
    for cat in categories:
        calls, label = _CAT_ESTIMATES[cat]
        print(f'  Category {cat}: ~{calls:>3} calls   ({label})')
        total_calls += calls
    print(f'  {"─" * 48}')
    print(f'  Total estimated LLM calls: ~{total_calls}  (gate failures are $0)')
    print(f'  Estimated cost at ${_COST_PER_CALL}/call:  ~${total_calls * _COST_PER_CALL:.2f}')
    print()
    answer = input('Proceed? [y/N]: ').strip().lower()
    return answer == 'y'


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_results(data: dict):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = RESULTS_DIR / f'ablation_{ts}.json'
    path.write_text(json.dumps(data, indent=2))
    print(f'\nFull results saved to {path}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ablation test harness for fitment engine')
    parser.add_argument('--category', type=int, choices=[1, 2, 3],
                        help='Run only this category (default: all)')
    args = parser.parse_args()

    categories = [args.category] if args.category else [1, 2, 3]

    if not print_cost_estimate(categories):
        print('Aborted.')
        raise SystemExit(0)

    jobs     = load_jobs()
    profiles = load_profiles()
    resumes  = load_resumes()

    output: dict = {
        'run_at': datetime.now(timezone.utc).isoformat(),
        'categories_run': categories,
    }

    if 1 in categories:
        output['category_1'] = run_category_1(jobs, profiles, resumes)
    if 2 in categories:
        output['category_2'] = run_category_2(jobs, profiles, resumes)
    if 3 in categories:
        output['category_3'] = run_category_3(jobs, profiles, resumes)

    # Grand total
    grand = _blank_totals()
    for cat_key in ['category_1', 'category_2', 'category_3']:
        if cat_key in output:
            t = output[cat_key]['totals']
            for k in ('input', 'output', 'cache_w', 'cache_r', 'cost', 'calls', 'gate_failures'):
                grand[k] += t[k]

    n = grand['calls']
    if n:
        print(f'\n{"=" * 80}')
        print(f'GRAND TOTAL  ({n} LLM calls, {grand["gate_failures"]} gate failures)')
        print(f'  Input tokens:  {grand["input"]:,}')
        print(f'  Output tokens: {grand["output"]:,}')
        if grand['cache_w']:
            print(f'  Cache writes:  {grand["cache_w"]:,}')
        if grand['cache_r']:
            print(f'  Cache reads:   {grand["cache_r"]:,}')
        print(f'  Total cost:    ${grand["cost"]:.5f}')
        print(f'  Avg per call:  ${grand["cost"] / n:.5f}')

    save_results(output)
