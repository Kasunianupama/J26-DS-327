// Synthetic published records, no HTTP, database or private data.
import test from 'node:test';
import assert from 'node:assert/strict';
import { validatePublishedV3Rows } from './publishedV3.mjs';

function fixture() {
  const rule = feature => ({feature, lower:0, upper:10, direction:'higher_is_riskier', rationale:'Synthetic rule'});
  const indicator = (feature,value) => ({feature,value,score:value*10,explanation:'Synthetic indicator'});
  return { output_id:'fictional-v3',farm_id:'FARM_X',assessment_date:'2026-08-20',contract_version:'3.0.0',
    source_output_id:'fictional-v2',source_object:'c4_output.farm_risk_assessment_v2',source_payload_sha256:'a'.repeat(64),
    research_only:true,live_warning_allowed:false,model_status:'provisional_two_domain_not_live_validated',
    provenance:{source:'published',core_version:null,availability:'unknown'},
    scoring_config:{version:'c4-v3-climate-operational-1',source_scoring_version:'fictional-v2-version',climate_weight:.5,operational_weight:.5,
      medium_starts_at:30,high_starts_at:70,climate_rules:[rule('absolute_exceedance')],
      operational_rules:[rule('n_blood_alarms'),rule('n_conductivity_alarms')]},
    domains:[{domain:'climate',status:'available',configured_indicators:1,available_indicators:1,score:50,explanation:'Synthetic climate',indicators:[indicator('absolute_exceedance',5)]},
      {domain:'operational',status:'available',configured_indicators:2,available_indicators:2,score:60,explanation:'Mean',indicators:[indicator('n_blood_alarms',10),indicator('n_conductivity_alarms',2)]}],
    combined_score:55,contributions:{climate:25,operational:30},available_domains:2,risk_category:'medium_provisional',data_completeness:'complete',explanations:['Provisional research only']};
}
test('valid V3 is returned unchanged; empty stays empty',()=>{
  const row=fixture(), before=JSON.stringify(row);
  assert.equal(validatePublishedV3Rows([row])[0],row);
  assert.equal(JSON.stringify(row),before); assert.deepEqual(validatePublishedV3Rows([]),[]);
});
test('legacy records and inconsistent calculations never substitute for V3',()=>{
  for(const mutate of [r=>r.contract_version='1.1.0',r=>r.combined_score=48.4,r=>r.domains[1].score=100,
    r=>r.contributions.biological=0,r=>r.live_warning_allowed=true,r=>r.scoring_config.climate_weight=.4]){
    const row=fixture();mutate(row);assert.throws(()=>validatePublishedV3Rows([row]));
  }
});
test('duplicate dates and missing required values reject fabricated completeness',()=>{
  const row=fixture();assert.throws(()=>validatePublishedV3Rows([row,row]));
  row.domains[1].indicators[1].value=null;
  assert.throws(()=>validatePublishedV3Rows([row]));
});
