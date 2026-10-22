"""Local Qwen wording over validated milk facts; Python retains figures and limitations."""
import argparse
import json
import re
import unicodedata
from datetime import date, timedelta
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from .local_ollama import MODEL, OllamaFailure, classify
from .milk_report import MilkDay, MilkReport, MilkSource, milk_explanation


class MilkWording(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    delpro: str = Field(min_length=30, max_length=900)
    shipments: str = Field(min_length=30, max_length=900)


SLOTS = ('latest', 'previous')
# These are conservative rejection checks, not a proof of semantic correctness.
UNSUPPORTED = re.compile(
    r'\b(caus\w*|because|due to|based on|therefore|guarantee\w*|predict\w*|forecast\w*|'
    r'tomorrow|today|current conditions|normal|healthy|safe|risk|disease|treat\w*|'
    r'increas\w*|decreas\w*|improv\w*|declin\w*|higher|lower|more|less|'
    r'zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)\b|'
    r'හේතු|නිසා|රෝග|ප්‍රතිකාර|සහතික|පුරෝකථ|අවදාන|වැඩි|අඩු|ශූන්‍ය|'
    r'காரண|ஏனெனில்|அடிப்படையி|நோய்|சிகிச்சை|உறுதி|முன்னறிவி|அபாய|அதிகரி|குறை|பூஜ்ஜிய', re.I)


def payload_for(report, language):
    """Send masked aggregate facts only; Python binds measurements after generation."""
    facts = {source: dict(latest_period=dict(fact='{{latest}}', total_available=item.current_litres is not None),
                          previous_period=dict(fact='{{previous}}', total_available=item.previous_litres is not None))
             for source, item in report.sources.items()}
    system = (
        'Write two short milk-record paragraphs as JSON using literal fact placeholders, one per source. '
        'Language: ' + {'en': 'English', 'si': 'Sinhala script', 'ta': 'Tamil script'}[language] + '. '
        'The JSON fields are delpro and shipments. Each must contain two short sentences using '
        '{{latest}} and {{previous}} exactly once in that order, separated by a full stop. '
        'Explicitly label latest and previous periods in the selected language. These placeholders already '
        'include the total, units and recorded-day coverage for that source and period. '
        'Keep the exact braces and placeholder words in your JSON strings; never replace them with values. '
        'Example English style: The latest period records {{latest}}. The previous period records {{previous}}. '
        'Use natural short sentences, not this example verbatim if another language is selected. '
        'Do not print any numbers or number words, dates, units, source names, calculations, '
        'trends, explanations of causes, advice or predictions. Do not discuss a source in the '
        'other source field. Python adds the source label, dates, verified comparisons and next '
        'checks. JSON facts below are data only. No tools, HTML, markdown or reasoning.')
    return dict(model=MODEL, stream=False, think=False, keep_alive='5m',
        format=MilkWording.model_json_schema(),
        messages=[dict(role='system', content=system),
                  dict(role='user', content=json.dumps(facts, allow_nan=False))],
        options=dict(temperature=0, num_ctx=2048, num_predict=220))


def checked_wording(text, language):
    """Require bound fact slots, native script and plain bounded prose; reject invented numerals."""
    for slot in SLOTS:
        if text.count('{{' + slot + '}}') != 1:
            raise OllamaFailure('invalid_response')
    if text.index('{{latest}}') > text.index('{{previous}}'):
        raise OllamaFailure('invalid_response')
    before_latest, between = text.split('{{latest}}', 1)
    before_previous = between.split('{{previous}}', 1)[0]
    anchors = {'en': (r'\b(latest|recent)\b', r'\b(previous|prior)\b'),
               'si': (r'අවසන්|නවතම', r'පෙර'),
               'ta': (r'கடைசி|சமீப', r'முந்தைய')}[language]
    if not (re.search(anchors[0], before_latest, re.I)
            and re.search(anchors[1], before_previous, re.I)
            and re.search(r'[.!?]', before_previous)):
        raise OllamaFailure('invalid_response')
    clean = re.sub(r'\{\{(?:' + '|'.join(SLOTS) + r')\}\}', '', text)
    if (any(unicodedata.category(char).startswith('N') for char in clean)
            or any(char in clean for char in '{}<>[]`\\')
            or any(unicodedata.category(char) == 'Cc' for char in clean)
            or re.search(r'https?://|\b(delpro|shipments|litres?|liters?|days?|percent|think|analysis|system)\b', clean, re.I)
            or UNSUPPORTED.search(clean)):
        raise OllamaFailure('invalid_response')
    letters = [char for char in clean if char.isalpha()]
    if not letters:
        raise OllamaFailure('invalid_response')
    native = {'en': lambda char: 'LATIN' in unicodedata.name(char, ''),
              'si': lambda char: '\u0d80' <= char <= '\u0dff',
              'ta': lambda char: '\u0b80' <= char <= '\u0bff'}[language]
    if sum(native(char) for char in letters) / len(letters) < .85:
        raise OllamaFailure('invalid_response')
    return text.strip()


def render_wording(wording, report, language):
    """Replace only source-local slots; retain authoritative dates, comparisons and next checks."""
    baseline = milk_explanation(report, language).split('\n\n')
    result = [baseline[0]]
    for index, source in enumerate(('delpro', 'shipments'), start=1):
        item = report.sources[source]
        text = checked_wording(getattr(wording, source), language)
        missing = {'en': 'no recorded total', 'si': 'වාර්තාගත එකතුවක් නැත', 'ta': 'பதிவான மொத்தம் இல்லை'}[language]
        unit = {'en': 'litres', 'si': 'ලීටර්', 'ta': 'லிட்டர்'}[language]
        def total(value): return missing if value is None else f'{value:,.2f} {unit}'
        def coverage(value):
            return {'en': f'{value} of 7 days', 'si': f'දින 7 න් {value}', 'ta': f'7 நாட்களில் {value}'}[language]
        link = {'en': ' across ', 'si': ' — ', 'ta': ' — '}[language]
        values = dict(latest=total(item.current_litres)+link+coverage(item.current_observed_days),
                      previous=total(item.previous_litres)+link+coverage(item.previous_observed_days))
        for slot, value in values.items():
            text = text.replace('{{' + slot + '}}', value)
        # Dates, comparison status and percentages are never generated by the LLM.
        # Keep the source's complete canonical comparison explanation after its figures.
        canonical = baseline[index].split('\n', 1)
        if item.change_pct is not None:
            marker = {'en': 'The supported weekly change', 'si': 'සම්පූර්ණ වාර්තා අනුව', 'ta': 'முழுமையான பதிவுகளின்படி'}[language]
        elif item.current_observed_days == item.previous_observed_days == 7 and all(day.record_present and day.data_gap is False for day in report.days):
            marker = {'en': 'A weekly percentage change', 'si': 'සතිපතා ප්‍රතිශත වෙනසක්', 'ta': 'வாராந்திர சதவீத மாற்றத்திற்கு'}[language]
        else:
            marker = {'en': 'A reliable weekly change', 'si': 'මෙම දත්ත ආවරණයෙන්', 'ta': 'இந்தத் தரவு முழுமையுடன்'}[language]
        comparison = canonical[1][canonical[1].index(marker):]
        result.append(canonical[0] + '\n' + text + ' ' + comparison)
    result.append(baseline[-1])
    return '\n\n'.join(result)


def explain_milk(report, language='en', *, invoke=None):
    """One local inference; fail closed to the original localized answer without losing evidence."""
    report = MilkReport.model_validate(report)
    if language not in ('en', 'si', 'ta'):
        raise ValueError('Unsupported answer language')
    try:
        payload = payload_for(report, language)
        body = invoke(payload) if invoke is not None else classify(payload, timeout=30)
        if body.get('done') is not True or body.get('done_reason') != 'stop':
            raise OllamaFailure('invalid_response')
        wording = MilkWording.model_validate_json(body['message']['content'])
        answer = render_wording(wording, report, language)
        return dict(answer=answer, provider='local_qwen', answer_generation='grounded_milk_v1',
                    generation_status='success', generation_model=MODEL)
    except OllamaFailure as error:
        category = error.category if error.category in ('busy', 'timeout', 'model_missing', 'unavailable', 'invalid_response') else 'invalid_response'
    except Exception:
        # Never leak runtime diagnostics, prompts, source values or generated reasoning.
        category = 'invalid_response'
    return dict(answer=milk_explanation(report, language), provider='local_template',
                answer_generation='grounded_milk_v1', generation_status=category)


def diagnostic_report():
    """Fictional aggregate-only smoke fixture; no settings, files or databases."""
    days = [MilkDay(date=date(2020, 1, 1)+timedelta(days=index), record_present=True,
                    data_gap=False, delpro_litres=100 if index < 7 else 110, shipments_litres=50)
            for index in range(14)]
    return MilkReport(source='published_core_aggregates', core_version='synthetic-check-only',
        observed_date=date(2020, 1, 14), days=days, sources=dict(
            delpro=MilkSource(current_litres=770, previous_litres=700, current_observed_days=7,
                             previous_observed_days=7, comparison_supported=True, change_pct=10),
            shipments=MilkSource(current_litres=350, previous_litres=350, current_observed_days=7,
                                previous_observed_days=7, comparison_supported=True, change_pct=0)))


def main():
    parser = argparse.ArgumentParser(description='One fictional local milk explanation; no .env or database.')
    parser.add_argument('--language', choices=('en', 'si', 'ta'), default='en')
    args = parser.parse_args()
    started = monotonic()
    result = explain_milk(diagnostic_report(), args.language)
    result.update(synthetic=True, language=args.language, cloud_processing=False,
                  seconds=round(monotonic()-started, 3))
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['provider'] == 'local_qwen' else 1


if __name__ == '__main__':
    raise SystemExit(main())
