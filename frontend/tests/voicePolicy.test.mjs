// Offline speech policy checks; never record audio, enumerate real voices or call APIs.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url);
const ts=require('typescript');
const js=ts.transpileModule(readFileSync(new URL('../src/pages/Assistant/voicePolicy.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const module={exports:{}};new Function('module','exports',js)(module,module.exports);
const {localSpeechEndpoint,localEnglishVoice}=module.exports;
test('audio accepts explicit loopback endpoints and same-machine relative APIs',()=>{
  for(const base of ['http://localhost:8000/api/v1','http://127.0.0.1:8000/api/v1','http://[::1]:8000/api/v1','/api/v1']) assert.equal(localSpeechEndpoint(base,'http://localhost:5173/assistant'),true);
});
test('remote, disguised, credential-bearing and unsupported URLs cannot receive speech',()=>{
  for(const base of ['https://external.invalid/api','http://localhost.external.invalid/api','http://user:password@localhost/api','file:///api','not a valid url']) assert.equal(localSpeechEndpoint(base,'https://remote.invalid/assistant'),false);
  assert.equal(localSpeechEndpoint('/api','https://remote.invalid/assistant'),false);
});
test('playback never chooses a remote default when a local English voice exists',()=>{
  const local={lang:'en-GB',localService:true};
  assert.equal(localEnglishVoice([{lang:'en-US',localService:false},local]),local);
});
test('missing local English voices cannot fall back to remote or another language',()=>{
  assert.equal(localEnglishVoice([{lang:'en-US',localService:false},{lang:'de-DE',localService:true}]),undefined);
  assert.equal(localEnglishVoice([]),undefined);
});
