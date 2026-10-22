"""Digital Agronomist demo chat and explicit local published aggregate briefing."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from components.member3_farmer_reasoning.services.demo_service import answer_query
from components.member3_farmer_reasoning.services.published_service import load_published_brief
from components.member3_farmer_reasoning.services.local_risk_chat import LocalRiskQuery, answer_local_risk
from components.member3_farmer_reasoning.services.local_chat import ChatQuery, answer_chat
from components.member3_farmer_reasoning.services.local_voice import voice_status, transcribe_audio, VoiceError, MAX_AUDIO_BYTES
from components.member3_farmer_reasoning.services.milk_report import MilkExportRequest
from components.member3_farmer_reasoning.services.milk_xlsx import milk_workbook
from shared.schemas.user import UserRole
from shared.schemas.predictive import PredictiveFarmContext

router = APIRouter(prefix='/agent', tags=['digital-agronomist'])


class AgentQuery(BaseModel):
    query: str
    farm_id: str
    role: UserRole = UserRole.FARM_MANAGER
    language: str = 'en'
    predictive_context: PredictiveFarmContext | None = None
    conversation_id: str | None = None


@router.post('/query')
def query_agent(request: AgentQuery) -> dict:
    return answer_query(request.query, request.farm_id, request.role, request.language,
                        request.predictive_context, request.conversation_id)


@router.get('/briefing')
def published_briefing() -> dict:
    """Read local aggregate facts only; fail visibly without a synthetic fallback."""
    try:
        return load_published_brief()
    except Exception:
        # Driver diagnostics may contain secrets or data; keep them out of responses.
        raise HTTPException(status_code=503, detail=
            'Published data unavailable. Check C3 configuration, permissions and published tables locally.') from None


@router.post('/local-query')
def local_query(request: LocalRiskQuery) -> dict:
    """Local C4 facts and templates only; this endpoint has no hosted provider."""
    return answer_local_risk(request)


@router.post('/chat')
def local_chat(request: ChatQuery) -> dict:
    """Single real-data C3 entry point; no demo or hosted provider fallback."""
    return answer_chat(request)


@router.get('/voice/status')
def local_voice_status() -> dict:
    """Check speech files/dependencies only; never open a database or download."""
    return voice_status()


@router.post('/voice/transcribe')
async def local_voice_transcribe(request: Request, language: Literal['en', 'si', 'ta'] = 'en') -> dict:
    """Bounded in-memory audio, processed on this backend's local CPU only."""
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail='Record a short question within the 6 MB limit.')
        audio.extend(chunk)
    try:
        return await run_in_threadpool(transcribe_audio, bytes(audio), language, request.headers.get('content-type', ''))
    except VoiceError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.post('/reports/milk.xlsx')
def download_milk_report(request: MilkExportRequest) -> Response:
    """Export the validated displayed snapshot; never query a database or rerun a model."""
    payload = milk_workbook(request.report, request.language)
    return Response(payload, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="farm-x-milk-{request.report.observed_date}.xlsx"',
                 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
