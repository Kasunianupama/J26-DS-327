"""Human-run Gemini evaluation using fixed synthetic fixtures only; never farm data."""
import argparse
import json
import os
from pathlib import Path
import re
from time import perf_counter

import httpx
from pydantic import ValidationError

from components.member3_farmer_reasoning.schemas.tool_contracts import ToolCall
from .tool_router import INPUTS as ALL_INPUTS
from .synthetic_tools import synthetic_router

# Keep the approved six-case hosted evaluation unchanged; C4 stays local.
INPUTS = {name: ALL_INPUTS[name] for name in ('core_summary', 'c1_forecast', 'c2_simulation')}

LANGUAGES = dict(en='English', si='Sinhala', ta='Tamil')
FACTS = ('A fictional farm recorded milk on 6 of 7 days. A complete weekly comparison '
         'is unavailable. Do not invent a missing value, missing date or percentage change.')
CASES = [dict(id='explain_'+code, language=code, task='explanation',
             question=f'Explain this in two short sentences in {name} only. '
                      f'Use its normal script and retain the digits 6 and 7: {FACTS}')
         for code, name in LANGUAGES.items()]
CASES += [
    dict(id='route_core_en', language='en', task='routing', expected_tool='core_summary',
         expected_status='success', expected_arguments=dict(topic='herd'), question='Show the latest recorded herd count for a fictional farm.'),
    dict(id='route_forecast_si', language='si', task='routing', expected_tool='c1_forecast',
         expected_status='success', expected_arguments=dict(reference_date='2020-01-01', target_period='2020-01-02', grain='daily', series='herd_milk'), question='කල්පිත ගොවිපළක 2020-01-02 දිනයේ කිරි පුරෝකථනය පෙන්වන්න. '
         'Reference date: 2020-01-01. Grain: daily. Series: herd_milk. Model: pfoi-1.2.0-dev.'),
    dict(id='route_simulation_ta', language='ta', task='routing', expected_tool='c2_simulation',
         expected_status='needs_input', expected_arguments=dict(intervention='feed', change_percent=10), expected_missing=['horizon_days'], question='ஒரு கற்பனைப் பண்ணையில் தீவனத்தை 10% அதிகரித்தால் என்ன நடக்கும்?'),
]


class EvaluationError(RuntimeError):
    """Sanitized failure with a category, never provider bodies or request secrets."""
    def __init__(self, message, category='provider_response'):
        super().__init__(message)
        self.category = category


def make_prompt(case):
    if case['task'] == 'explanation':
        return ('Synthetic evaluation, not real farm data. Return exactly one JSON object '
                'with only an answer string. No planning text or reasoning trace.\n' + case['question'])
    schemas = {name: model.model_json_schema() for name, model in INPUTS.items()}
    return ('Synthetic tool-selection test. Return only JSON with tool and arguments. '
            'Do not answer the question, execute tools, write SQL or invent missing inputs. '
            'Choose only core_summary, c1_forecast or c2_simulation. Use topic=herd for herd counts; '
            'topic=weather for weather. Forecast model defaults to pfoi-1.2.0-dev. '
            'For a feed change use intervention=feed and the stated numeric change_percent; '
            'omit horizon_days if not provided so the local router asks for it. '
            'All tool fields are described by these C3-owned provisional schemas:\n'
            + json.dumps(schemas, ensure_ascii=False) + '\nQuestion:\n' + case['question'])


def response_schema(case):
    """Constrain the envelope; missing tool inputs stay optional for clarification."""
    if case['task'] == 'explanation':
        return dict(type='object', properties=dict(answer=dict(type='string')),
                    required=['answer'], additionalProperties=False)
    properties = {}
    for model in INPUTS.values():
        for name, field in model.model_json_schema()['properties'].items():
            field = {key:value for key, value in field.items() if key not in ('default', 'title')}
            if 'const' in field:
                field['enum'] = [field.pop('const')]
            properties[name] = field
    return dict(type='object', properties=dict(
        tool=dict(type='string', enum=list(INPUTS)),
        arguments=dict(type='object', properties=properties, additionalProperties=False)),
        required=['tool', 'arguments'], additionalProperties=False)

def generate(client, model, api_key, case):
    """Send only a fixture; classify failures without leaking provider diagnostics."""
    if not re.fullmatch(r'[A-Za-z0-9._-]+', model):
        raise EvaluationError('Invalid model identifier.', 'configuration')
    if not isinstance(api_key, str) or not api_key.strip():
        raise EvaluationError('Set GEMINI_API_KEY privately before a live run.', 'configuration')
    body = dict(contents=[dict(role='user', parts=[dict(text=make_prompt(case))])],
                generationConfig=dict(temperature=0, maxOutputTokens=1024,
                                      responseMimeType='application/json',
                                      responseJsonSchema=response_schema(case)))
    started = perf_counter()
    try:
        response = client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': api_key}, json=body)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hints = {400:'Check model support and request settings.',
                 401:'Check the API key privately.',
                 403:'Check API key restrictions, project permissions or region access.',
                 404:'Check the model name and availability for your account.',
                 429:'Check the project quota and rate limits; do not enable billing automatically.'}
        raise EvaluationError(f'Gemini HTTP {code}. ' + hints.get(code, 'Provider returned an HTTP error.'), 'http_error') from None
    except httpx.TimeoutException:
        raise EvaluationError('Gemini request timed out. Check connection and provider latency; no automatic retry was made.', 'timeout') from None
    except httpx.ConnectError as exc:
        # Inspect for a known marker only; never echo the underlying diagnostic.
        tls = any(marker in str(exc).lower() for marker in ('certificate verify failed', 'certificate_verify_failed'))
        if tls:
            raise EvaluationError('TLS certificate verification failed. Check local certificates or network inspection; do not disable verification.', 'tls') from None
        raise EvaluationError('Could not connect to Gemini. Check DNS, internet access and firewall settings. API key validity is not established.', 'connection') from None
    except httpx.HTTPError:
        raise EvaluationError('Gemini transport failed before a usable response. No automatic retry was made.', 'transport') from None
    except (ValueError, TypeError):
        raise EvaluationError('Request could not be constructed. Check the private key format and local configuration.', 'request_configuration') from None
    try:
        payload = response.json()
    except ValueError:
        raise EvaluationError('The server returned non-JSON content instead of a Gemini API response.', 'response_format') from None
    try:
        if payload.get('promptFeedback', {}).get('blockReason'):
            raise EvaluationError('Provider blocked the synthetic prompt; no final answer was returned.', 'provider_blocked')
        candidate = payload['candidates'][0]
        reason = candidate.get('finishReason')
        if reason != 'STOP':
            if reason == 'MAX_TOKENS':
                raise EvaluationError('Response reached its output-token limit before completion.', 'output_limit')
            raise EvaluationError('Provider did not return a completed final answer.', 'generation_incomplete')
        text = ''.join(part.get('text', '') for part in candidate['content']['parts']
                       if not part.get('thought', False))
        if not text.strip():
            raise EvaluationError('Provider returned no final answer text.', 'empty_answer')
    except (KeyError, IndexError, TypeError, AttributeError):
        raise EvaluationError('JSON response did not contain the expected Gemini candidate text. Check model/API compatibility.', 'response_shape') from None
    usage = payload.get('usageMetadata') or {}
    return text, round(perf_counter()-started, 3), usage if isinstance(usage, dict) else {}

def script_matches(text, language):
    """Script sanity check only; it does not assess fluency or factual correctness."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    if language == 'en':
        hits = sum('a' <= char.lower() <= 'z' for char in letters)
    else:
        low, high = (0x0D80, 0x0DFF) if language == 'si' else (0x0B80, 0x0BFF)
        hits = sum(low <= ord(char) <= high for char in letters)
    return hits/len(letters) >= .8


def assess(case, text):
    """Validate JSON and routing with synthetic tools; always require human review."""
    try:
        data = json.loads(text)
        if case['task'] == 'explanation':
            if not isinstance(data, dict) or set(data) != {'answer'} or not isinstance(data['answer'], str):
                raise ValueError
            answer = data['answer']
            numbers = set(re.findall(r'\d+', answer))
            return dict(format_ok=True, answer=answer,
                        script_matches=script_matches(answer, case['language']),
                        supplied_digits_preserved={'6', '7'} <= numbers,
                        unexpected_digits=sorted(numbers-{'1', '6', '7'}),
                        human_review_required=True)
        call = ToolCall.model_validate(data)
        outcome = synthetic_router().execute(call.model_dump())
        return dict(format_ok=True, selected_tool=call.tool,
                    arguments=call.arguments, router_status=outcome.status,
                    routing_matches=(call.tool == case['expected_tool'] and outcome.status == case['expected_status']
                        and all(call.arguments.get(key) == value for key, value in case['expected_arguments'].items())
                        and outcome.missing_fields == case.get('expected_missing', [])),
                    missing_fields=outcome.missing_fields, synthetic_tools_only=True,
                    human_review_required=True)
    except ValidationError:
        return dict(format_ok=False, error_category='tool_contract', human_review_required=True)
    except (ValueError, TypeError):
        return dict(format_ok=False, error_category='response_json', human_review_required=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Synthetic-only Gemini evaluation; no database access.')
    parser.add_argument('--live', action='store_true', help='Explicitly send selected synthetic cases to Gemini.')
    parser.add_argument('--model', help='Exact Gemini model available to your account; no automatic fallback.')
    parser.add_argument('--case', choices=[case['id'] for case in CASES], help='Run one case before the full suite.')
    args = parser.parse_args(argv)
    cases = [case for case in CASES if not args.case or case['id'] == args.case]
    if not args.live:
        print(json.dumps(dict(mode='preview', provider='gemini', requests=0,
            cases=[dict(id=c['id'], language=c['language'], task=c['task']) for c in cases]), indent=2))
        return 0
    if not args.model:
        parser.error('--live requires --model; choose an available model explicitly.')
    # The operator, not an AI agent, runs this branch. No other local config is sent.
    from dotenv import dotenv_values
    private_settings = dotenv_values(Path(__file__).resolve().parents[3] / '.env', interpolate=False)
    api_key = os.environ.get('GEMINI_API_KEY') or private_settings.get('GEMINI_API_KEY')
    if not api_key:
        print('Set GEMINI_API_KEY privately in the application .env or shell. Never share it.')
        return 1
    completed = 0
    with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
        for case in cases:
            try:
                text, seconds, usage = generate(client, args.model, api_key, case)
            except EvaluationError as exc:
                print(json.dumps(dict(case=case['id'], status='error', message=str(exc), error_category=exc.category,
                    completed_requests=completed)))
                return 1
            result = dict(case=case['id'], provider='gemini', model=args.model,
                synthetic=True, seconds=seconds, checks=assess(case, text),
                usage={key:usage.get(key) for key in ('promptTokenCount', 'candidatesTokenCount', 'totalTokenCount')})
            print(json.dumps(result, ensure_ascii=False))
            completed += 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
