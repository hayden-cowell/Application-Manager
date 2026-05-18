from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from schemas import ScoreRequest, FitAssessment, OverrideRequest, AssessmentResponse
from scorer import score_job
from storage import save_assessment, get_assessment, list_assessments
from prompts import PROMPT_VERSION

app = FastAPI(title='Fitment Engine', version='1.0')


@app.post('/assess', response_model=AssessmentResponse)
async def assess(request: ScoreRequest):
    try:
        assessment, token_usage = score_job(request)
        if request.save_result:
            save_assessment(assessment)
        return AssessmentResponse(assessment=assessment, token_usage=token_usage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/assessments', response_model=list[FitAssessment])
async def get_assessments():
    return list_assessments()


@app.get('/assessments/{assessment_id}', response_model=FitAssessment)
async def get_single(assessment_id: str):
    result = get_assessment(assessment_id)
    if not result:
        raise HTTPException(status_code=404, detail='Assessment not found')
    return result


@app.post('/assessments/{assessment_id}/override')
async def override(assessment_id: str, body: OverrideRequest):
    assessment = get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail='Not found')
    assessment.user_overridden = True
    assessment.override_action = body.action
    save_assessment(assessment)
    return {'status': 'logged'}


@app.get('/health')
async def health():
    return {'status': 'ok', 'prompt_version': PROMPT_VERSION}
