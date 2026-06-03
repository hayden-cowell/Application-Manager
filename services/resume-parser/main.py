import sys
import os

# Must happen before any local imports that depend on fitment-engine schemas
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'fitment-engine'))

from dotenv import load_dotenv
load_dotenv()

import json
import logging

from fastapi import FastAPI, HTTPException

from parse_schemas import ParseRequest, ParseResponse, FollowupRequest, FollowupResponse
from parser import parse_resume
from parse_storage import save_profile, save_resume, get_profile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title='Resume Parser', version='1.0')


@app.post('/parse', response_model=ParseResponse)
async def parse(request: ParseRequest):
    try:
        profile, resume, quality, warnings, followup = parse_resume(
            request.input_type,
            request.content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail='Parser LLM returned malformed JSON.')
    except Exception as e:
        logger.exception('Unexpected error during parse')
        raise HTTPException(status_code=500, detail=str(e))

    save_profile(profile)
    save_resume(resume)

    return ParseResponse(
        profile=profile,
        resume=resume,
        parse_quality=quality,
        parse_warnings=warnings,
        fields_requiring_followup=followup,
    )


@app.post('/parse/followup', response_model=FollowupResponse)
async def followup(request: FollowupRequest):
    profile = get_profile(request.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail='Profile not found.')

    # Merge answers into profile
    try:
        updated = profile.model_copy(update=request.answers)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Invalid answer fields: {e}')

    # Strip self_assessed_gaps entries that duplicate a confirmed_false skill
    confirmed_false_names = {s.name for s in updated.skills if not s.confirmed}
    updated = updated.model_copy(update={
        'self_assessed_gaps': [
            g for g in updated.self_assessed_gaps
            if g not in confirmed_false_names
        ]
    })

    save_profile(updated)
    return FollowupResponse(profile=updated)


@app.get('/health')
async def health():
    return {'status': 'ok'}
