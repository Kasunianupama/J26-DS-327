// Offline static-language and history checks using fictional values only.
import {test} from 'node:test';import assert from 'node:assert/strict';
import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);const ts=require('typescript');
function load(name){const module={exports:{}};const js=ts.transpileModule(readFileSync(new URL(`../src/pages/Assistant/${name}.ts`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;new Function('module','exports',js)(module,module.exports);return module.exports;}
const {t,message}=load('i18n');const {emptyHistory,decodeHistory}=load('chatHistory');const {localVoice}=load('voicePolicy');
test('all main chat actions and evidence labels have Sinhala and Tamil copy',()=>{
 for(const key of ['Digital Agronomist','Chat history','Send question','Add dates','View evidence & dates','Records through','Total animals','Reference date','Not supplied','Research only','Back up whole profile','What would you like to understand?']) for(const language of ['si','ta']) {
   assert.notEqual(t(language,key),key);assert.match(t(language,key),language==='si'?/[\u0d80-\u0dff]/:/[\u0b80-\u0bff]/);
 }
});
test('technical versions and supplied values are never translated',()=>{
 for(const language of ['en','si','ta']) for(const value of ['pfoi-1.2.0-dev','2020-01-01','100.25']) assert.equal(t(language,value),value);
});
test('history retains selected language, and older conversations remain readable',()=>{
 const state=emptyHistory('synthetic');state.conversations[0].language='ta';
 assert.equal(decodeHistory(JSON.stringify(state)).conversations[0].language,'ta');
 delete state.conversations[0].language;assert.equal(decodeHistory(JSON.stringify(state)).conversations.length,1);
 state.conversations[0].language='unsupported';assert.throws(()=>decodeHistory(JSON.stringify(state)));
});
test('read-aloud cannot silently use English or remote voices for Sinhala/Tamil answers',()=>{
 const tamil={lang:'ta-IN',localService:true};const english={lang:'en-US',localService:true};
 assert.equal(localVoice([english,tamil],'ta'),tamil);
 assert.equal(localVoice([english,{lang:'si-LK',localService:false}],'si'),undefined);
});


test('localized confirmations preserve profile labels and counts literally',()=>{
 for(const language of ['si','ta']) {
  const label='Profile {scope} 2';
  const text=message(language,'Clear chats for {scope} only? This also clears its open conversation.',{scope:label});
  assert.ok(text.includes(label));assert.ok(!text.startsWith('Clear chats'));
  const notice=message(language,'Restored {added} conversations. Kept {skipped} existing conversations with matching IDs. Other profile and role histories were preserved.',{added:3,skipped:2});
  assert.ok(notice.includes('3') && notice.includes('2'));
 }
});
