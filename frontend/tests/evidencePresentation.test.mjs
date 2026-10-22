// Render only fictional evidence; no browser, API, settings or database access.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url), ts=require('typescript');
const React=require('react'), {renderToStaticMarkup}=require('react-dom/server');
const cache=new Map();
function load(name){
  if(cache.has(name))return cache.get(name);
  const extension=name==='i18n'?'.ts':'.tsx';
  const js=ts.transpileModule(readFileSync(new URL(`../src/pages/Assistant/${name}${extension}`,import.meta.url),'utf8'),
    {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const module={exports:{}};
  new Function('require','module','exports',js)(id=>id.startsWith('./')?load(id.slice(2)):require(id),module,module.exports);
  cache.set(name,module.exports);return module.exports;
}
const {EvidencePanel}=load('EvidencePanel'), {EvidenceCautions}=load('EvidenceCautions'), {t}=load('i18n');
const evidence=Object.freeze({kind:'c4_risk',demo:false,assessment_date:'2020-01-02',reference_date:'2020-01-03',
  combined_score:25,research_only:true,live_warning_allowed:false,source:'c4_output.farm_risk_assessment_v1',contract_version:'1.1.0'});
test('C4 restrictions remain intact inside a closed technical disclosure',()=>{
  const html=renderToStaticMarkup(React.createElement(EvidencePanel,{evidence}));
  const cutoff=html.indexOf('<details class="c3-proof-provenance">');
  assert.ok(cutoff>0);assert.match(html.slice(cutoff),/Research only/);assert.match(html.slice(cutoff),/Live warnings permitted/);
  assert.doesNotMatch(html.slice(0,cutoff),/Research only|Live warnings permitted|Selected as of/);
  assert.equal(evidence.research_only,true);assert.equal(evidence.live_warning_allowed,false);
  assert.match(html,/25/);assert.doesNotMatch(html,/open=""/);
});
test('plain C4 limitation stays visible and every original warning remains accessible',()=>{
  const warnings=['Synthetic source compatibility note','Synthetic producer disallows live warnings'];
  const html=renderToStaticMarkup(React.createElement(EvidenceCautions,{reply:{evidence,warnings},language:'en'}));
  const cutoff=html.indexOf('<details');assert.match(html.slice(0,cutoff),/cannot provide live alerts or confirm causes/);
  for(const warning of warnings)assert.ok(html.slice(cutoff).includes(warning));
  assert.doesNotMatch(html,/open=""/);
});
test('forecast points outside bounds cannot be hidden among technical notes',()=>{
  const html=renderToStaticMarkup(React.createElement(EvidenceCautions,{reply:{evidence:{kind:'c1_forecast',forecast:100,lower:80,upper:90},warnings:['Synthetic note']},language:'en'}));
  assert.match(html.slice(0,html.indexOf('<details')),/outside the supplied range and needs review/);
});
test('core data coverage warnings stay directly visible',()=>{
  const html=renderToStaticMarkup(React.createElement(EvidenceCautions,{reply:{evidence:{source:'published_core_aggregates'},warnings:['Only 6 of 7 days supplied']},language:'en'}));
  assert.match(html,/Only 6 of 7 days supplied/);assert.doesNotMatch(html,/<details/);
});
test('new farmer-facing copy is available in Sinhala and Tamil',()=>{
  for(const language of ['si','ta'])for(const key of ['Forecast date','Review older records','Technical notes','Technical source details',
    'Historical research result. It cannot provide live alerts or confirm causes.','The forecast falls outside the supplied range and needs review.'])assert.notEqual(t(language,key),key);
});
