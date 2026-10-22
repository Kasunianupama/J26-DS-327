"""Fictional C4 explanation checks; never open settings, databases or models."""
from copy import deepcopy
import pytest
from components.member3_farmer_reasoning.services.risk_explanation import explain_risk
from components.member3_farmer_reasoning.services.local_chat import answer_chat, ChatQuery
from components.member3_farmer_reasoning.tests.test_local_risk_chat import outcome, router


def evidence(**changes):
    return outcome(climate_score=10,biological_score=0,operational_score=20,**changes).evidence.model_dump(mode='json')


@pytest.mark.parametrize('language,marker', [('en','Suggested record checks:'),('si','ඊළඟට පරීක්ෂා කළ හැකි වාර්තා:'),('ta','பரிந்துரைக்கப்படும் பதிவுச் சரிபார்ப்புகள்:')])
def test_meaning_review_steps_scores_and_dates_are_distinct_in_every_language(language,marker):
    source=evidence();unchanged=deepcopy(source)
    answer=explain_risk(source,language)
    sections=answer.split('\n\n')
    assert len(sections)==4 and marker in sections[1]
    assert sections[1].count('• ')==4
    assert all(value in answer for value in ['2020-01-08','2020-01-10','2020-02-01','25.00','10.00','0.00','20.00'])
    assert '25.00' not in sections[0] and '25.00' in sections[2]
    assert source==unchanged


def test_review_suggestions_are_not_presented_as_producer_recommendations():
    answer=explain_risk(evidence())
    assert 'general review suggestions, not actions prescribed by the score' in answer
    assert 'cannot label this score high or low' in answer
    assert 'zero score does not confirm that conditions were normal' in answer
    assert 'rank its components as causes' in answer
    assert '%' not in answer and '/100' not in answer


@pytest.mark.parametrize('language,zero_phrase', [('en','zero score'),('si','ශූන්‍ය ලකුණකින්'),('ta','பூஜ்ஜிய மதிப்பெண்')])
def test_zero_is_explained_without_treating_it_as_missing_or_normal(language,zero_phrase):
    answer=explain_risk(evidence(),language)
    assert zero_phrase in answer
    assert '0.00' in answer


def test_absent_component_scores_do_not_create_reasons_for_review_or_fabricated_values():
    source=outcome(climate_score=None,biological_score=None,operational_score=None,combined_score=None).evidence.model_dump(mode='json')
    answer=explain_risk(source)
    assert 'combined score is unavailable' in answer
    review=answer.split('\n\n')[1]
    assert review.count('• ')==1
    assert 'temperature' not in review and 'farm-operation' not in review and 'herd events' not in review
    assert '0.00' not in answer and 'zero score' not in answer


def test_scores_are_not_clamped_or_converted_to_percentages():
    source=outcome(climate_score=9000.5,biological_score=None,operational_score=-12.25).evidence.model_dump(mode='json')
    answer=explain_risk(source)
    assert '9,000.50' in answer and '-12.25' in answer
    assert '%' not in answer and '/100' not in answer


@pytest.mark.parametrize('language', ['en','si','ta'])
def test_unified_chat_preserves_evidence_flags_warnings_and_generated_date(language):
    supplied=outcome(climate_score=10,biological_score=0,operational_score=20)
    reply=answer_chat(ChatQuery(query='C4 historical assessment for 2020-01-10',language=language),risk_router=router(supplied))
    assert reply['status']=='success' and reply['cloud_processing'] is False
    assert reply['evidence']['research_only'] is True and reply['evidence']['live_warning_allowed'] is False
    assert reply['evidence']['generated_at'].startswith('2020-02-01')
    assert reply['evidence']['biological_score']==0
    assert reply['answer']==explain_risk(reply['evidence'],language)
    assert reply['warnings']


def test_unknown_generation_time_is_not_invented():
    source=outcome(generated_at=None).evidence.model_dump(mode='json')
    answer=explain_risk(source)
    assert 'generation time is not supplied' in answer and 'Generated on' not in answer


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError):explain_risk(evidence(),'unsupported')
