"""Bounded English question routing to local C4 research evidence; no LLM calls."""
from datetime import date
import re

from pydantic import BaseModel, ConfigDict, Field

from .c4_repository import local_c4_router


class LocalRiskQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1500)
    reference_date: date | None = None


def reply(status, answer, **fields):
    return dict(status=status, answer=answer, provider='local_template',
                cloud_processing=False, demo=False, **fields)


def answer_local_risk(request, router=None):
    """Resolve only C4 history questions, without exposing identifiers or payloads."""
    text = request.query.lower()
    if not re.search(r'\b(c4|risk|assessment|assessments)\b', text):
        return reply('unsupported', 'This local view currently explains C4 historical research assessments. Ask about C4 and provide one reference date.')
    if re.search(r'\b(today|tonight|tomorrow|now|current|live|alert|alerts|warning|warnings)\b', text):
        return reply('unavailable', 'C4 is connected for historical research explanation only. Its imported assessments are not approved for live warnings or current alerts.')
    dates = set(re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', request.query))
    if len(dates) > 1:
        return reply('needs_input', 'Please request one historical date at a time in YYYY-MM-DD format.', missing_fields=['reference_date'])
    parsed_date = None
    if dates:
        try:
            parsed_date = date.fromisoformat(next(iter(dates)))
        except ValueError:
            return reply('invalid_request', 'That date is invalid. Use a calendar date in YYYY-MM-DD format.')
    if parsed_date and request.reference_date and parsed_date != request.reference_date:
        return reply('needs_input', 'The question date and selected reference date differ. Please choose one date.', missing_fields=['reference_date'])
    reference = parsed_date or request.reference_date
    if reference is None:
        return reply('needs_input', 'Which historical date should I use? Select a reference date or include YYYY-MM-DD in your question.', missing_fields=['reference_date'])
    try:
        outcome = (router or local_c4_router()).execute(dict(tool='c4_risk', arguments=dict(
            reference_date=reference.isoformat(), purpose='historical_explanation')))
    except Exception:
        return reply('error', 'Local C4 retrieval failed. Check local settings and permissions; no substitute answer was generated.')
    if outcome.status != 'success' or outcome.evidence is None:
        return reply(outcome.status, 'A validated C4 historical assessment is unavailable for that request. Check coverage, permissions and duplicate records. No demo or cloud fallback was used.')
    evidence = outcome.evidence
    if evidence.kind != 'c4_risk' or evidence.demo:
        return reply('invalid_result', 'The tool did not return real C4 historical evidence. No substitute answer was generated.')
    from .risk_explanation import explain_risk
    answer = explain_risk(evidence.model_dump(mode='json'))
    warnings = list(evidence.warnings)
    if evidence.assessment_cutoff is None:
        warnings.append('Assessment cutoff is not supplied in the export.')
    return reply('success', answer, tool='c4_risk',
                 evidence=evidence.model_dump(mode='json'), warnings=warnings)
