// Fictional milk snapshots only; no browser API, database, real records or network.
import {test} from 'node:test';import assert from 'node:assert/strict';
import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server'),cache=new Map();
function load(name){
 if(cache.has(name))return cache.get(name);
 const extension=name==='MilkReportView'?'.tsx':'.ts',module={exports:{}};
 const js=ts.transpileModule(readFileSync(new URL(`../src/pages/Assistant/${name}${extension}`,import.meta.url),'utf8'),
  {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 new Function('require','module','exports',js)(id=>id==='../../services/api'?{api:{post(){throw new Error('No network');}}}:id.startsWith('./')?load(id.slice(2)):require(id),module,module.exports);
 cache.set(name,module.exports);return module.exports;
}
const {milkReport,lineSegments}=load('milkReport'),{MilkReportView}=load('MilkReportView');
function fixture(){return {kind:'milk_summary',version:1,source:'published_core_aggregates',core_version:'fictional-v1',observed_date:'2020-01-14',warnings:[],
 days:Array.from({length:14},(_,index)=>({date:new Date(Date.UTC(2020,0,index+1)).toISOString().slice(0,10),record_present:true,data_gap:false,delpro_litres:index<7?100:110,shipments_litres:50})),
 sources:{delpro:{current_litres:770,previous_litres:700,current_observed_days:7,previous_observed_days:7,comparison_supported:true,change_pct:10},shipments:{current_litres:350,previous_litres:350,current_observed_days:7,previous_observed_days:7,comparison_supported:true,change_pct:0}}};}
test('saved report stays intact across history serialization',()=>{const report=fixture();assert.deepEqual(milkReport(JSON.parse(JSON.stringify({milk_report:report}))),report);});
test('invalid, incomplete or duplicate date series cannot render a report',()=>{
 for(const mutate of [report=>report.days.pop(),report=>report.days[1].date='2020-01-01',report=>report.days[0].delpro_litres=NaN,report=>report.days[0].record_present=false,report=>report.version=99,report=>report.sources.delpro.current_litres=999,report=>report.sources.delpro.change_pct=99]){
  const report=fixture();mutate(report);assert.equal(milkReport({milk_report:report}),null);
 }
 assert.equal(milkReport({}),null);
});
test('line paths break at missing values and keep a genuine zero',()=>{
 const days=fixture().days.slice(0,4);days[1].shipments_litres=null;days[2].shipments_litres=0;
 const paths=lineSegments(days,'shipments_litres',index=>index,value=>value);
 assert.equal(paths.length,2);assert.equal(paths[0],'M0.00,50.00');assert.equal(paths[1],'M2.00,0.00 L3.00,50.00');
});
test('chart and source cards present separate figures without adding sources',()=>{
 const html=renderToStaticMarkup(React.createElement(MilkReportView,{evidence:{milk_report:fixture()},language:'en'}));
 assert.match(html,/770/);assert.match(html,/350/);assert.match(html,/\+10%/);assert.match(html,/Download Excel/);
 assert.match(html,/They are not added together/);assert.match(html,/<svg/);assert.match(html,/<table>/);
 assert.doesNotMatch(html,/1,120/);
});
test('missing milk is shown as not recorded while shipments zero stays zero',()=>{
 const report=fixture();report.days[13].delpro_litres=null;report.days[13].shipments_litres=0;
 Object.assign(report.sources.delpro,{current_litres:660,current_observed_days:6,comparison_supported:false,change_pct:null});
 Object.assign(report.sources.shipments,{current_litres:300,comparison_supported:false,change_pct:null});
 const html=renderToStaticMarkup(React.createElement(MilkReportView,{evidence:{milk_report:report},language:'en'}));
 assert.match(html,/<td>Not recorded<\/td><td>0<\/td>/);
});
test('new chart and download labels are translated in both native languages',()=>{
 const {t}=load('i18n');for(const language of ['si','ta'])for(const key of ['Download Excel','Daily milk and weekly comparison','Comparison unavailable','View daily figures','Not recorded'])assert.notEqual(t(language,key),key);
});
