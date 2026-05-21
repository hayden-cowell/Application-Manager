"""
Migrates existing profile JSON files from PM-specific boolean flags to the
role-agnostic Skill list schema.

Usage:
  python migrate_profiles.py              # migrate all profiles in data/profiles/
  python migrate_profiles.py --dry-run    # print changes without writing
"""
import argparse
import json
from pathlib import Path

PROFILES_DIR = Path('data/profiles')

LEGACY_FLAG_TO_SKILL = {
    'has_platform_product_experience':    'platform product management',
    'has_pricing_experience':             'pricing and packaging',
    'has_growth_experience':              'growth experimentation',
    'has_0_to_1_experience':              '0 to 1 product development',
    'has_owned_revenue_metric':           'revenue metric ownership',
    'has_owned_retention_metric':         'retention metric ownership',
    'has_worked_with_sales':              'sales-assisted GTM',
    'has_enterprise_experience':          'enterprise product management',
    'has_scaling_experience':             'scaling existing products',
    'has_management_experience':          'people management',
    'can_write_code':                     'software development',
    'comfortable_with_data':              'data analysis',
    'has_consumer_experience':            'consumer product management',
    'has_smb_experience':                 'SMB product management',
    'has_director_or_above_experience':   'director or above leadership',
    'has_launched_products':              'product launches',
    'has_worked_with_legal_compliance':   'legal and compliance',
    'budget_ownership':                   'budget ownership',
    'vendor_management':                  'vendor management',
    'has_mba':                            'MBA',
    'has_published_work':                 'published work',
    'has_conference_speaking':            'conference speaking',
    'has_notable_side_projects':          'notable side projects',
    'has_exec_exposure':                  'executive exposure',
    'strong_in_discovery':                'product discovery',
    'strong_in_delivery':                 'product delivery',
    'strong_in_strategy':                 'product strategy',
    'strong_in_growth':                   'growth strategy',
    'has_internationalization_experience': 'internationalization',
    'has_worked_embedded_with_engineering': 'embedded engineering partnership',
    'has_written_technical_specs':        'technical specification writing',
    'can_read_code':                      'code reading',
}


def migrate_profile(data: dict) -> dict:
    skills = []
    unanswered_skills = []

    for flag, skill_name in LEGACY_FLAG_TO_SKILL.items():
        if flag not in data:
            continue
        val = data.pop(flag)
        if val is True:
            skills.append({'name': skill_name, 'confirmed': True})
        elif val is False:
            skills.append({'name': skill_name, 'confirmed': False})
        else:
            unanswered_skills.append(skill_name)

    data['skills'] = skills
    data['unanswered_skills'] = unanswered_skills
    return data


def main(dry_run: bool):
    paths = sorted(PROFILES_DIR.glob('*.json'))
    if not paths:
        print(f'No profile JSONs found in {PROFILES_DIR}')
        return

    for path in paths:
        original = json.loads(path.read_text(encoding='utf-8'))
        migrated = migrate_profile(dict(original))

        skills_true  = [s['name'] for s in migrated['skills'] if s['confirmed']]
        skills_false = [s['name'] for s in migrated['skills'] if not s['confirmed']]
        unanswered   = migrated['unanswered_skills']

        print(f'\n{path.name}')
        print(f'  confirmed_true  ({len(skills_true)}): {skills_true}')
        print(f'  confirmed_false ({len(skills_false)}): {skills_false}')
        print(f'  unanswered      ({len(unanswered)}): {unanswered}')

        if not dry_run:
            path.write_text(json.dumps(migrated, indent=2), encoding='utf-8')
            print(f'  -> written')
        else:
            print(f'  -> DRY RUN: not written')

    if not dry_run:
        print(f'\nMigration complete. {len(paths)} profile(s) updated.')
    else:
        print(f'\nDry run complete. {len(paths)} profile(s) would be updated.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Print changes without writing')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
