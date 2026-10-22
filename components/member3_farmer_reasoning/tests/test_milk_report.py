"""Fictional milk-report tests for source separation, coverage and snapshot export integrity."""
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from components.member3_farmer_reasoning.services.milk_report import build_milk_report, MilkReport, milk_explanation
from components.member3_farmer_reasoning.services.milk_xlsx import milk_workbook
from components.member3_farmer_reasoning.services.aggregate_brief import build_brief
from components.member3_farmer_reasoning.services.local_chat import answer_chat, ChatQuery
from components.member3_farmer_reasoning.tests.test_aggregate_brief import context


def report_context():
    source=context()
    source['milk_daily']=[dict(day=date(2020,1,1)+timedelta(days=index),source_rows=1,data_gap=False,
        delpro_litres=100 if index<7 else 110,shipments_litres=50) for index in range(14)]
    return source


def report_fixture():return build_milk_report(build_brief(report_context()))


def test_daily_figures_reconcile_and_never_combine_the_two_sources():
    report=report_fixture()
    assert len(report.days)==14 and report.sources['delpro'].current_litres==770
    assert report.sources['shipments'].current_litres==350
    assert report.sources['delpro'].change_pct==10 and report.sources['shipments'].change_pct==0


def test_missing_day_is_a_gap_not_a_zero_or_fabricated_observation():
    source=report_context();source['milk_daily'].pop()
    source['current_period'].update(observed_days=6,delpro_days=6,delpro_litres=660,shipment_days=6,shipment_litres=300)
    report=build_milk_report(build_brief(source))
    assert report.days[-1].record_present is False and report.days[-1].delpro_litres is None
    assert report.days[-1].shipments_litres is None and report.days[-1].data_gap is None
    assert all(item.change_pct is None for item in report.sources.values())


@pytest.mark.parametrize('flag',[True,None])
def test_flagged_or_unknown_gap_status_withholds_growth_even_with_values(flag):
    source=report_context();source['milk_daily'][-1]['data_gap']=flag
    report=build_milk_report(build_brief(source))
    assert report.days[-1].delpro_litres==110
    assert report.sources['delpro'].change_pct is None and not report.sources['delpro'].comparison_supported


def test_real_shipment_zero_remains_numeric_and_zero_baseline_has_no_growth():
    source=report_context()
    for row in source['milk_daily']:row['shipments_litres']=0
    for period in ('current_period','previous_period'):source[period]['shipment_litres']=0
    report=build_milk_report(build_brief(source))
    assert report.days[0].shipments_litres==0
    assert report.sources['shipments'].current_observed_days==7 and report.sources['shipments'].change_pct is None


@pytest.mark.parametrize('alteration',['duplicate','wrong-total','wrong-count','nonfinite','wrong-date'])
def test_inconsistent_daily_source_cannot_generate_a_report(alteration):
    source=report_context()
    if alteration=='duplicate':source['milk_daily'].append(source['milk_daily'][0])
    elif alteration=='wrong-total':source['milk_daily'][-1]['delpro_litres']=111
    elif alteration=='wrong-count':source['milk_daily'][-1]['source_rows']=2
    elif alteration=='nonfinite':source['milk_daily'][-1]['delpro_litres']=float('nan')
    else:source['milk_daily'][-1]['day']=date(2021,1,1)
    with pytest.raises(ValueError):build_milk_report(build_brief(source))


@pytest.mark.parametrize('alteration',['total','change','coverage','date','missing-as-zero'])
def test_modified_download_snapshot_is_revalidated(alteration):
    payload=report_fixture().model_dump(mode='json')
    if alteration=='total':payload['sources']['delpro']['current_litres']=1234
    elif alteration=='change':payload['sources']['delpro']['change_pct']=99
    elif alteration=='coverage':payload['days'][-1]['data_gap']=True
    elif alteration=='date':payload['days'][-1]['date']='2020-01-13'
    else:payload['days'][-1]['record_present']=False
    with pytest.raises(ValueError):MilkReport.model_validate(payload)


@pytest.mark.parametrize('language',['en','si','ta'])
def test_chart_export_and_localized_answer_share_the_same_snapshot(language):
    brief=build_brief(report_context());expected=build_milk_report(brief)
    result=answer_chat(ChatQuery(query='Compare recorded milk weeks',language=language),briefing=lambda:brief)
    assert result['status']=='success' and result['cloud_processing'] is False
    assert result['evidence']['milk_report']==expected.model_dump(mode='json')
    assert result['answer']==milk_explanation(expected,language)
    assert all(value in result['answer'] for value in ['770.00','700.00','350.00','2020-01-08','2020-01-14'])


def test_daily_evidence_failure_cannot_silently_fallback_to_old_totals():
    source=report_context();source['milk_daily'][-1]['delpro_litres']=999
    result=answer_chat(ChatQuery(query='Milk summary'),briefing=lambda:build_brief(source))
    assert result['status']=='unavailable' and 'evidence' not in result


def test_legacy_summary_without_daily_history_is_not_given_a_fake_chart():
    brief=build_brief(context())
    assert build_milk_report(brief) is None
    result=answer_chat(ChatQuery(query='Milk summary'),briefing=lambda:brief)
    assert result['status']=='success' and 'milk_report' not in result['evidence']


def test_workbook_is_native_typed_xlsx_and_does_not_change_the_snapshot():
    report=report_fixture();saved=deepcopy(report.model_dump())
    payload=milk_workbook(report,'si')
    assert payload.startswith(b'PK') and report.model_dump()==saved
    with ZipFile(BytesIO(payload)) as archive:
        root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'));ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        assert root.find('.//s:c[@r="B6"]/s:v',ns).text=='770.0'
        assert root.find('.//s:c[@r="B10"]/s:v',ns).text=='0.1'
        assert root.find('.//s:c[@r="B2"]',ns).get('s')=='5'
        assert all('external' not in name.lower() and 'vba' not in name.lower() for name in archive.namelist())
        assert 'වාර්තාගත කිරි සාරාංශය'.encode() in archive.read('xl/worksheets/sheet1.xml')


def test_workbook_preserves_blank_daily_values_and_literal_text_injection():
    source=report_context();source['milk_daily'][-1]['delpro_litres']=None
    source['current_period'].update(delpro_days=6,delpro_litres=660)
    report=build_milk_report(build_brief(source))
    report.warnings.append('=HYPERLINK("https://example.invalid","literal")')
    with ZipFile(BytesIO(milk_workbook(report))) as archive:
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        daily=ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        assert daily.find('.//s:c[@r="C18"]',ns) is None
        for name in ['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml']:
            assert ET.fromstring(archive.read(name)).find('.//s:f',ns) is None


def test_export_endpoint_uses_submitted_snapshot_without_rerunning_a_data_tool(monkeypatch):
    from backend.app.api.routes import agent
    reader=Mock(side_effect=AssertionError('No reread'))
    monkeypatch.setattr(agent,'answer_chat',reader);monkeypatch.setattr(agent,'load_published_brief',reader)
    app=FastAPI();app.include_router(agent.router,prefix='/api/v1')
    result=TestClient(app).post('/api/v1/agent/reports/milk.xlsx',json=dict(report=report_fixture().model_dump(mode='json'),language='ta'))
    assert result.status_code==200 and result.content.startswith(b'PK')
    assert result.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert 'farm-x-milk-2020-01-14.xlsx' in result.headers['content-disposition']
    reader.assert_not_called()


def test_export_api_rejects_tampered_totals_and_unknown_paths():
    from backend.app.api.routes import agent
    app=FastAPI();app.include_router(agent.router,prefix='/api/v1');client=TestClient(app)
    payload=report_fixture().model_dump(mode='json');payload['sources']['delpro']['current_litres']=1234
    assert client.post('/api/v1/agent/reports/milk.xlsx',json=dict(report=payload)).status_code==422
    assert client.post('/api/v1/agent/reports/milk.xlsx',json=dict(report=report_fixture().model_dump(mode='json'),path='unapproved')).status_code==422


def test_complete_zero_baseline_is_not_described_as_missing_data():
    source=report_context()
    for row in source['milk_daily']:row['shipments_litres']=0
    for period in ('current_period','previous_period'):source[period]['shipment_litres']=0
    report=build_milk_report(build_brief(source));answer=milk_explanation(report)
    assert 'positive previous total' in answer
    assert 'Check missing daily entries' not in answer
    assert '0.00 litres recorded across 7 of 7 days' in answer


def test_no_measurements_have_plain_missing_total_wording():
    source=report_context()
    for row in source['milk_daily']:row['shipments_litres']=None
    for period in ('current_period','previous_period'):source[period].update(shipment_days=0,shipment_litres=None)
    answer=milk_explanation(build_milk_report(build_brief(source)))
    assert 'No milk total was recorded for this period' in answer
    assert 'not recorded litres' not in answer
