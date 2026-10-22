// Synthetic saved-chat context checks for automatic C2 follow-ups and legacy compatibility.
import {test} from 'node:test';import assert from 'node:assert/strict';
import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url),ts=require('typescript'),module={exports:{}};
const js=ts.transpileModule(readFileSync(new URL('../src/pages/Assistant/chatHistory.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('module','exports',js)(module,module.exports);
const {emptyHistory,decodeHistory}=module.exports;
test('a partially specified what-if survives refresh for an ordinary chat follow-up',()=>{
 const state=emptyHistory('fictional');state.conversations[0].context={topic:'simulation',awaiting:'simulation_cow',scenario:{animal_ref:null,thi_mean:68,milkings_per_day:null,mode:'thi'}};
 assert.deepEqual(decodeHistory(JSON.stringify(state)).conversations[0].context,state.conversations[0].context);
});
test('context proposals are bounded input fields, with no paths, arbitrary tools or invalid numbers',()=>{
 for(const scenario of [{model_path:'unapproved'},{animal_ref:'source-id'},{animal_ref:'A_PLACEHOLDER'},{milkings_per_day:0},{thi_mean:'68'},{mode:'unapproved'},{thi_mean:true}]) {
  const state=emptyHistory('fictional');state.conversations[0].context={topic:'simulation',scenario};assert.throws(()=>decodeHistory(JSON.stringify(state)));
 }
});
test('normal and older conversations remain readable without a simulation context',()=>{
 const state=emptyHistory('fictional');assert.equal(decodeHistory(JSON.stringify(state)).conversations.length,1);
 state.conversations[0].context={topic:'herd',scenario:null};assert.equal(decodeHistory(JSON.stringify(state)).conversations[0].context.scenario,null);
});
test('the chat no longer exposes or submits a separate simulator form',()=>{
 const source=readFileSync(new URL('../src/pages/Assistant/LocalAssistant.tsx',import.meta.url),'utf8');
 assert.ok(!source.includes('SimulationForm'));assert.ok(!source.includes('simulation?: ScenarioInput'));
 assert.ok(source.includes('Reply with the missing cow or scenario detail…'));
});
