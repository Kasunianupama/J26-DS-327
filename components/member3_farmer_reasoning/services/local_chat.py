"""Fast local rules and factual multilingual answers; no chat-time Qwen inference."""
from datetime import date
from math import isfinite
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .c2_gateway import ScenarioInput
from .c2_dialogue import ScenarioDraft, simulation_intent, is_followup, reference_reply
from .c2_chat import reply as simulation_reply
from .published_service import load_published_brief
from .c1_repository import read_forecast
from .c4_repository import local_c4_router
from .local_risk_chat import LocalRiskQuery, answer_local_risk
from ..orchestration.tool_router import ToolRouter, Adapter


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: Literal['herd', 'milk', 'weather', 'forecast', 'risk', 'simulation'] | None = None
    reference_date: date | None = None
    target_period: date | None = None
    grain: Literal['daily', 'weekly', 'monthly'] = 'daily'
    series: Literal['herd_milk', 'n_herd', 'milking', 'calvings', 'dry_offs', 'real_abortions'] = 'herd_milk'
    awaiting: Literal['reference_date', 'target_period','simulation_cow','simulation_thi','simulation_milkings','simulation_value','simulation_feature'] | None = None
    scenario: ScenarioDraft | None = None


class ChatQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1500)
    language: Literal['en', 'si', 'ta'] = 'en'
    simulation: ScenarioInput | None = None
    context: ConversationContext = Field(default_factory=ConversationContext)
    reference_date: date | None = None
    target_period: date | None = None
    grain: Literal['daily', 'weekly', 'monthly'] | None = None


def number(value, digits=0):
    if value is None:
        return 'not supplied'
    if not isfinite(float(value)):
        raise ValueError('Non-finite measurement.')
    return f'{value:,.{digits}f}'


def response(context, status, answer, **fields):
    return dict(status=status, answer=answer, context=context.model_dump(mode='json'),
                provider='local_template', cloud_processing=False, demo=False, **fields)


def identify(text):
    if simulation_intent(text):
        return 'simulation'
    from .language_interpreter import english_topic
    return english_topic(text)


def _answer_english(request, *, briefing=None, forecast_router=None, risk_router=None, simulation_invoke=None, original_query=None):
    """Client carries bounded follow-up parameters only; no server conversation store."""
    context = request.context.model_copy(deep=True)
    text = request.query.lower()
    topic = identify(text)
    if request.simulation is not None and topic != 'simulation':
        return response(context, 'invalid_request', 'Explicit what-if intent is required before running a simulation.')
    # Only short/date-only follow-ups inherit intent. Unrelated questions never do.
    dates = re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)', text)
    followup = bool(re.fullmatch(r'\s*(?:\d{4}-\d{2}-\d{2}|daily|weekly|monthly|and that|same date)[?.! ]*', text))
    if topic is None and followup:
        topic = context.topic
    if topic is None:
        return response(context, 'unsupported', 'I can help with recorded herd, milk and weather summaries, stored forecasts, historical risk assessments and simulator availability. Please ask one clear farm-data question in English, Sinhala or Tamil.')
    if context.topic != topic:
        context = ConversationContext(topic=topic)
    else:
        context.topic = topic
    if topic == 'simulation':
        return simulation_reply(request, context, invoke=simulation_invoke, query_text=original_query)
    if re.search(r'\b(which (?:cows|animals)|individual|animal history|per[- ]cow)\b', text):
        return response(context, 'unsupported', 'This chat currently reads herd-level aggregates only. Individual animal histories and attention lists are not connected.')
    if topic in ('herd', 'milk', 'weather') and re.search(r'\b(tomorrow|next|future)\b', text):
        return response(context, 'unsupported', 'Recorded summaries cannot answer a future question. Ask for a stored forecast and supply reference and target dates; weather forecasts are not connected.')
    if re.search(r'\b(why|cause|caused|diagnos\w*|treat\w*)\b', text):
        return response(context, 'unsupported', 'These records and experimental outputs cannot establish a cause or diagnosis. Ask for a recorded summary, a stored forecast or a historical assessment instead.')
    if len(set(dates)) > 1:
        return response(context, 'needs_input', 'Please set the reference date and forecast target separately using Add dates. I will not guess which date has which role.')
    if dates:
        try:
            parsed = date.fromisoformat(dates[0])
        except ValueError:
            return response(context, 'invalid_request', 'That date is invalid. Please use YYYY-MM-DD.')
        slot = context.awaiting or ('target_period' if topic == 'forecast' else 'reference_date')
        explicit = getattr(request, slot)
        if explicit and explicit != parsed:
            return response(context, 'needs_input', 'The date in your question differs from the date control. Please make them match.')
        setattr(context, slot, parsed)
        context.awaiting = None
    for field in ('reference_date', 'target_period', 'grain'):
        value = getattr(request, field)
        if value is not None:
            setattr(context, field, value)
    for term, grain in [('daily', 'daily'), ('weekly', 'weekly'), ('monthly', 'monthly')]:
        if re.search(r'\b' + term + r'\b', text):
            context.grain = grain
    if topic == 'forecast':
        if re.search(r'\b(herd size|total herd)\b', text):
            context.series = 'n_herd'
        elif re.search(r'\bmilking\b', text):
            context.series = 'milking'
        elif re.search(r'\bcalvings?\b', text):
            context.series = 'calvings'
        elif re.search(r'\bdry[- ]offs?\b', text):
            context.series = 'dry_offs'
        elif re.search(r'\babortions?\b', text):
            context.series = 'real_abortions'
        elif re.search(r'\bmilk\b', text):
            context.series = 'herd_milk'
    if topic in ('forecast', 'risk'):
        if topic == 'risk' and re.search(r'\b(today|tomorrow|current|live|now|alerts?|warnings?)\b', text):
            return response(context, 'unavailable', 'C4 assessments are retrospective research only. They cannot provide current alerts or live warnings.')
        for field in (['target_period'] if topic == 'forecast' else ['reference_date']):
            if getattr(context, field) is None:
                context.awaiting = field
                prompt = ('Which reference date should I use? This selects forecasts originating on or before that date.' if topic == 'forecast' and field == 'reference_date' else
                          'Which day would you like the forecast for? Choose Forecast date or reply with YYYY-MM-DD. I will select the latest stored forecast covering that day; weekly and monthly forecasts must match their stored period date.' if field == 'target_period' else
                          'Which past day would you like to review? Choose Past day to review or reply with YYYY-MM-DD.')
                return response(context, 'needs_input', prompt, missing_fields=[field])
    context.awaiting = None
    try:
        if topic == 'risk':
            reply = answer_local_risk(LocalRiskQuery(query='C4 historical assessment', reference_date=context.reference_date), router=risk_router or local_c4_router())
            return response(context, reply['status'], reply['answer'], title='Historical risk assessment',
                            evidence=reply.get('evidence'), warnings=reply.get('warnings', []), tool='c4_risk')
        if topic == 'forecast':
            router = forecast_router or ToolRouter(dict(c1_forecast=Adapter(read_forecast, False)))
            outcome = router.execute(dict(tool='c1_forecast', arguments=dict(
                # Automatic cutoff is never after today or the requested forecast period.
                # Explicit historical cutoffs remain supported; inferred ones are not persisted.
                model_version='pfoi-1.2.0-dev', reference_date=context.reference_date or min(date.today(), context.target_period),
                target_period=context.target_period, grain=context.grain, series=context.series)))
            if outcome.status != 'success' or outcome.evidence is None or outcome.evidence.demo:
                return response(context, 'unavailable', 'No unique validated forecast is available for those dates, period and series. Check stored coverage and local permissions; no substitute model or value was used.', title='Stored forecast')
            evidence = outcome.evidence
            unit = ' litres' if evidence.series == 'herd_milk' else ''
            answer = (f'The stored {evidence.grain} forecast for {evidence.target_period} is '
                      f'{number(evidence.forecast, 2)}{unit} for {evidence.series.replace("_", " ")}. '
                      f'The forecast is dated {evidence.origin_date}. ')
            answer += (f'The supplied bounds are {number(evidence.lower, 2)} to {number(evidence.upper, 2)}{unit}.'
                       if evidence.lower is not None and evidence.upper is not None else 'The supplied bounds are incomplete; no range was invented.')
            answer += ' This is a stored forecast, not a new run or a guaranteed outcome. Source compatibility with local core is unverified.'
            return response(context, 'success', answer, title='Stored forecast', tool='c1_forecast',
                            evidence=evidence.model_dump(mode='json'), warnings=evidence.warnings)
        brief = (briefing or load_published_brief)()
        if brief.get('demo') is not False or brief.get('source') != 'published_core_aggregates':
            raise ValueError('Unexpected briefing source.')
        observed = str(brief['observed_date'])
        if context.reference_date and str(context.reference_date) != observed:
            return response(context, 'unavailable', f'This summary reader currently supports the latest recorded date, {observed}. It cannot retrieve a different historical snapshot yet. Clear Add dates to request the latest recorded summary.')
        warnings = brief['warnings']
        evidence = dict(source=brief['source'], core_version=brief['core_version'], observed_date=observed)
        if topic == 'herd':
            herd = brief['herd']
            answer = (f'As of {observed}, the reconstructed herd contains {number(herd.get("total_animals"))} animals: '
                      f'{number(herd.get("milking"))} milking and {number(herd.get("dry"))} dry. '
                      'These are historical reconstructed counts, not current farm conditions.')
            evidence['herd'] = herd
        elif topic == 'weather':
            weather = brief['historical_weather']
            answer = (f'For {brief["latest_period"]["start"]} to {brief["latest_period"]["end"]}, '
                      f'{weather["complete_days"]} of 7 weather days are complete. '
                      f'Mean daily THI is {number(weather.get("mean_daily_thi"), 2)}; '
                      f'maximum hourly THI is {number(weather.get("max_hourly_thi"), 2)}. '
                      'These are historical reanalysis estimates, not farm measurements, a weather forecast or proof of a cause.')
            evidence.update(period=brief['latest_period'], weather=weather)
        else:
            sentences = [f'Latest recorded seven-day period: {brief["latest_period"]["start"]} to {brief["latest_period"]["end"]}.']
            for source, milk in brief['milk'].items():
                sentence = (f'{source.capitalize()}: {number(milk["current_litres"], 2)} litres recorded across '
                            f'{milk["current_observed_days"]} of 7 days; previous period: '
                            f'{number(milk["previous_litres"], 2)} litres across {milk["previous_observed_days"]} of 7 days. ')
                sentence += ('A reliable weekly change cannot be calculated from this coverage.' if milk['change_pct'] is None else
                             f'The supported weekly change is {number(milk["change_pct"], 2)}%.')
                sentences.append(sentence)
            answer = ' '.join(sentences) + ' Sources remain separate; partial totals are not complete weekly production.'
            evidence.update(latest_period=brief['latest_period'], previous_period=brief['previous_period'], milk=brief['milk'])
            from .milk_report import build_milk_report, milk_explanation
            report = build_milk_report(brief)
            if report is not None:
                evidence['milk_report'] = report.model_dump(mode='json')
                evidence['milk'] = {source: {**brief['milk'][source], 'change_pct': item.change_pct}
                                    for source, item in report.sources.items()}
                warnings = report.warnings
                answer = milk_explanation(report)

        return response(context, 'success', answer, title={'herd': 'Recorded herd summary', 'milk': 'Recorded milk comparison', 'weather': 'Historical weather'}[topic],
                        tool='core_summary', evidence=evidence, warnings=warnings)
    except Exception:
        return response(context, 'unavailable', 'The local data reader could not return validated evidence. Check the backend, restored outputs and local permissions. No demo or hosted fallback was used.')


def answer_chat(request, *, briefing=None, forecast_router=None, risk_router=None, language_planner=None, simulation_invoke=None):
    """Interpret locally, retain Python validation, and render facts in the selected language."""
    from .language_interpreter import normalize_question
    from .multilingual_answers import localize_reply
    question=reference_reply(request.query,request.context)
    if simulation_intent(question) or is_followup(question,request.context):
        normalized,mode='simulation '+question,'local_rules'
    else:
        normalized,mode=normalize_question(question,planner=language_planner)
    if mode.startswith('local_qwen_'):
        failure = mode.removeprefix('local_qwen_')
        explanation = {
            'timeout': 'The local language model took too long to interpret that wording.',
            'busy': 'The local language model is handling another question.',
            'model_missing': 'The local language model is not installed in Ollama.',
        }.get(failure, 'The local language model could not interpret that wording.')
        reply = response(request.context, 'unsupported', explanation +
            ' Try a shorter question or one of the suggested questions. No data tool was run.',
            interpretation_failure=failure)
        result = localize_reply(reply, request.language)
        result['interpretation_mode'] = mode
        return result
    english=request.model_copy(update=dict(query=normalized or 'unsupported language request'))
    reply=_answer_english(english,briefing=briefing,forecast_router=forecast_router,risk_router=risk_router,simulation_invoke=simulation_invoke,original_query=question)
    result=localize_reply(reply,request.language)
    # Qwen wording remains an offline experiment; viva answers use templates.
    result['interpretation_mode']=mode
    return result
