"""Validate one historical milk snapshot shared by narrative, chart and workbook export."""
from datetime import date, timedelta
from math import fsum, isclose
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class ReportModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class MilkDay(ReportModel):
    date: date
    delpro_litres: FiniteFloat | None = None
    shipments_litres: FiniteFloat | None = None
    record_present: bool = Field(strict=True)
    data_gap: bool | None = Field(default=None, strict=True)

    @model_validator(mode='after')
    def preserve_missingness(self):
        if not self.record_present and (self.delpro_litres is not None or self.shipments_litres is not None or self.data_gap is not None):
            raise ValueError('Absent records cannot contain measurements.')
        # Match the existing reader: a DelPro zero cannot establish an observation.
        if self.delpro_litres is not None and self.delpro_litres <= 0:
            raise ValueError('DelPro nonpositive values are not established observations.')
        return self


class MilkSource(ReportModel):
    current_litres: FiniteFloat | None
    previous_litres: FiniteFloat | None
    current_observed_days: int = Field(strict=True, ge=0, le=7)
    previous_observed_days: int = Field(strict=True, ge=0, le=7)
    comparison_supported: bool = Field(strict=True)
    change_pct: FiniteFloat | None


def close(left, right):
    return left is None and right is None or left is not None and right is not None and isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-6)


def totals(days, field):
    values = [getattr(day, field) for day in days if getattr(day, field) is not None]
    try:
        return len(values), fsum(values) if values else None
    except OverflowError:
        raise ValueError('Daily totals exceed finite support.') from None


class MilkReport(ReportModel):
    kind: Literal['milk_summary'] = 'milk_summary'
    version: Literal[1] = 1
    source: Literal['published_core_aggregates']
    core_version: str = Field(min_length=1, max_length=160)
    observed_date: date
    days: list[MilkDay] = Field(min_length=14, max_length=14)
    sources: dict[Literal['delpro', 'shipments'], MilkSource]
    warnings: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def reconcile_snapshot(self):
        if set(self.sources) != {'delpro', 'shipments'}:
            raise ValueError('Both separate milk sources are required.')
        expected = [self.observed_date - timedelta(days=13-index) for index in range(14)]
        if [day.date for day in self.days] != expected:
            raise ValueError('Exactly fourteen consecutive calendar days are required.')
        if any(len(warning) > 1000 for warning in self.warnings):
            raise ValueError('Oversized source note.')
        clear = all(day.record_present and day.data_gap is False for day in self.days)
        for source, summary in self.sources.items():
            field = 'delpro_litres' if source == 'delpro' else 'shipments_litres'
            previous_count, previous = totals(self.days[:7], field)
            current_count, current = totals(self.days[7:], field)
            if (previous_count != summary.previous_observed_days or current_count != summary.current_observed_days
                or not close(previous, summary.previous_litres) or not close(current, summary.current_litres)):
                raise ValueError('Daily evidence does not reconcile with the displayed totals.')
            usable = clear and previous_count == current_count == 7 and previous is not None and previous > 0
            if summary.comparison_supported and not usable:
                raise ValueError('Incomplete evidence cannot support a weekly comparison.')
            expected_change = (current-previous)/previous*100 if summary.comparison_supported else None
            if not close(summary.change_pct, expected_change):
                raise ValueError('Unsupported or mismatched weekly change.')
        return self


class MilkExportRequest(ReportModel):
    report: MilkReport
    language: Literal['en', 'si', 'ta'] = 'en'


def build_milk_report(brief):
    """Reconcile daily aggregates with the existing weekly reader; never refetch."""
    records = brief.get('milk_daily')
    if records is None:
        return None  # Earlier saved/fixture summaries have no daily evidence.
    observed = date.fromisoformat(str(brief['observed_date']))
    indexed = {}
    allowed = {observed-timedelta(days=offset) for offset in range(14)}
    for row in records:
        day = date.fromisoformat(str(row['day']))
        if day not in allowed or day in indexed or row['source_rows'] != 1:
            raise ValueError('Duplicate or unexpected daily aggregate.')
        indexed[day] = row
    days = []
    for index in range(14):
        day = observed-timedelta(days=13-index)
        row = indexed.get(day)
        days.append(MilkDay(date=day, record_present=row is not None,
            data_gap=row.get('data_gap') if row else None,
            delpro_litres=row.get('delpro_litres') if row else None,
            shipments_litres=row.get('shipments_litres') if row else None))
    clear = all(day.record_present and day.data_gap is False for day in days)
    sources = {}
    for source, old in brief['milk'].items():
        supported = old['change_pct'] is not None and clear
        sources[source] = MilkSource(**{key: old[key] for key in
            ('current_litres','previous_litres','current_observed_days','previous_observed_days')},
            comparison_supported=supported, change_pct=old['change_pct'] if supported else None)
    notes = [warning for warning in brief['warnings'] if warning.startswith(('Historical records', 'delpro:', 'shipments:'))]
    notes += ['DelPro and shipment measurements remain separate; do not add them together.',
              'Missing days remain blank. DelPro zero or absent totals cannot establish a recorded milk day.']
    if not clear:
        notes.append('Missing days, flagged gaps or unknown gap status prevent a complete weekly comparison.')
    return MilkReport(source=brief['source'], core_version=brief['core_version'], observed_date=observed,
                      days=days, sources=sources, warnings=notes)


def milk_explanation(report, language='en'):
    """Describe the same validated figures used in charts and exports, in three languages."""
    def w(en, si, ta): return {'en':en,'si':si,'ta':ta}[language]
    def n(value): return w('not recorded','වාර්තා වී නැත','பதிவாகவில்லை') if value is None else f'{value:,.2f}'
    start, end = report.days[7].date, report.observed_date
    sections = [w('Your recorded milk summary:', 'වාර්තාගත කිරි සාරාංශය:', 'பதிவான பால் சுருக்கம்:')+'\n'+w(
        f'Latest recorded seven-day period: {start} to {end}. These are historical records, not current farm conditions.',
        f'අවසන් වාර්තාගත දින හත: {start} සිට {end} දක්වා. මේවා අතීත වාර්තා වන අතර වත්මන් ගොවිපළ තත්ත්වය නොවේ.',
        f'கடைசிப் பதிவான ஏழு நாட்கள்: {start} முதல் {end} வரை. இவை கடந்தகாலப் பதிவுகள்; தற்போதைய பண்ணை நிலைமை அல்ல.')]
    for source in ('delpro', 'shipments'):
        item = report.sources[source]
        label = 'DelPro' if source=='delpro' else w('Milk shipments','කිරි නැව්ගත කිරීම්','பால் விநியோகப் பதிவுகள்')
        text = w(f'{n(item.current_litres)} litres recorded across {item.current_observed_days} of 7 days. ',
            f'දින 7 න් {item.current_observed_days} ක වාර්තාගත කිරි {n(item.current_litres)} ලීටර් ය. ',
            f'7 நாட்களில் {item.current_observed_days} நாட்களுக்கு {n(item.current_litres)} லிட்டர் பதிவாகியுள்ளது. ') if item.current_litres is not None else w(
            'No milk total was recorded for this period (0 of 7 days). ',
            'මෙම කාලයේ කිරි එකතුවක් වාර්තා වී නැත (දින 7 න් 0). ',
            'இந்தக் காலத்திற்கு பால் மொத்தம் பதிவாகவில்லை (7 நாட்களில் 0). ')
        text += w(f'Previous period: {n(item.previous_litres)} litres across {item.previous_observed_days} of 7 days. ',
            f'පෙර කාලයේ දින 7 න් {item.previous_observed_days} ක {n(item.previous_litres)} ලීටර් වාර්තා වී ඇත. ',
            f'முந்தைய காலத்தில் 7 நாட்களில் {item.previous_observed_days} நாட்களுக்கு {n(item.previous_litres)} லிட்டர் பதிவாகியுள்ளது. ') if item.previous_litres is not None else w(
            'No previous-period total was recorded. ','පෙර කාලයේ කිරි එකතුවක් වාර්තා වී නැත. ','முந்தைய காலத்தின் பால் மொத்தம் பதிவாகவில்லை. ')
        if item.change_pct is None:
            source_clear = item.current_observed_days == item.previous_observed_days == 7 and all(day.record_present and day.data_gap is False for day in report.days)
            if source_clear:
                text += w('A weekly percentage change needs a positive previous total. Use the recorded litre totals for this review; a reliable percentage comparison has not been established.',
                    'සතිපතා ප්‍රතිශත වෙනසක් සඳහා ධන පෙර එකතුවක් අවශ්‍යය. මෙම සමාලෝචනයට වාර්තාගත ලීටර් අගයන් භාවිතා කරන්න. විශ්වාසදායක ප්‍රතිශත සංසන්දනයක් තහවුරු වී නැත.',
                    'வாராந்திர சதவீத மாற்றத்திற்கு நேர்மறையான முந்தைய மொத்தம் தேவை. இந்த மீளாய்விற்கு பதிவான லிட்டர் மொத்தங்களைப் பயன்படுத்தவும். நம்பகமான சதவீத ஒப்பீடு உறுதிப்படுத்தப்படவில்லை.')
            else:
                text += w('A reliable weekly change cannot be calculated from this coverage. Incomplete totals must not be treated as complete weekly production.',
                'මෙම දත්ත ආවරණයෙන් විශ්වාසදායක සතිපතා වෙනසක් ගණනය කළ නොහැක. අර්ධ එකතුව සම්පූර්ණ සතියේ නිෂ්පාදනය ලෙස භාවිතා නොකරන්න.',
                'இந்தத் தரவு முழுமையுடன் நம்பகமான வாராந்திர மாற்றத்தைக் கணக்கிட முடியாது. இந்தப் பகுதி மொத்தத்தை முழு வார உற்பத்தியாகக் கருதக்கூடாது.')
        else:
            text += w(f'The supported weekly change is {item.change_pct:+.2f}%.',
                f'සම්පූර්ණ වාර්තා අනුව සතිපතා වෙනස {item.change_pct:+.2f}% ය.',
                f'முழுமையான பதிவுகளின்படி வாராந்திர மாற்றம் {item.change_pct:+.2f}%.')
        sections.append(label+':\n'+text)
    complete = all(item.comparison_supported for item in report.sources.values())
    missing = any(not day.record_present or day.data_gap is not False or day.delpro_litres is None or day.shipments_litres is None for day in report.days)
    next_step = w('Review days with visible changes against farm records before attributing a cause.',
        'හේතුවක් තීරණය කිරීමට පෙර ප්‍රස්තාරයේ වෙනස්කම් පෙනෙන දින ගොවිපළ වාර්තා සමඟ සසඳා බලන්න.',
        'காரணத்தைத் தீர்மானிக்கும் முன் வரைபடத்தில் மாற்றம் தெரியும் நாட்களை பண்ணைப் பதிவுகளுடன் ஒப்பிடவும்.') if complete else w(
        'Check missing daily entries and flagged gaps first. Reassess the weekly comparison after the underlying records are reviewed; do not fill gaps with zero.',
        'පළමුව අඩු දෛනික වාර්තා සහ සලකුණු කළ දත්ත හිඩැස් පරීක්ෂා කරන්න. මූලික වාර්තා සමාලෝචනය කළ පසු සතිපතා සංසන්දනය නැවත බලන්න. හිඩැස් ශූන්‍යයෙන් පුරවන්න එපා.',
        'முதலில் விடுபட்ட தினசரிப் பதிவுகளையும் குறிக்கப்பட்ட இடைவெளிகளையும் சரிபார்க்கவும். மூலப் பதிவுகளை மீளாய்வு செய்த பின் வாராந்திர ஒப்பீட்டை மீண்டும் பார்க்கவும். இடைவெளிகளை பூஜ்ஜியத்தால் நிரப்ப வேண்டாம்.')
    if not complete and not missing:
        next_step = w('Review the recorded litre totals directly. Check the previous-period total before relying on a percentage comparison.',
            'වාර්තාගත ලීටර් අගයන් කෙළින්ම සමාලෝචනය කරන්න. ප්‍රතිශත සංසන්දනයක් භාවිතා කිරීමට පෙර පෙර කාලයේ එකතුව පරීක්ෂා කරන්න.',
            'பதிவான லிட்டர் மொத்தங்களை நேரடியாக மீளாய்வு செய்யவும். சதவீத ஒப்பீட்டை நம்புவதற்கு முன் முந்தைய காலத்தின் மொத்தத்தைச் சரிபார்க்கவும்.')
    sections.append(w('What to check next:', 'ඊළඟට පරීක්ෂා කළ යුතු දේ:', 'அடுத்து சரிபார்க்க வேண்டியது:')+'\n'+next_step+' '+w(
        'Sources remain separate. Milk shipped can differ from milk recorded; these figures are not added together.',
        'මූලාශ්‍ර වෙන වෙනම තබා ඇත. නැව්ගත කළ කිරි සහ වාර්තාගත කිරි වෙනස් විය හැක. එම අගයන් එකතු කර නැත.',
        'மூலங்கள் தனித்தனியாக உள்ளன. விநியோகித்த பாலும் பதிவான பாலும் வேறுபடலாம். இவை ஒன்றாகக் கூட்டப்படவில்லை.'))
    return '\n\n'.join(sections)
