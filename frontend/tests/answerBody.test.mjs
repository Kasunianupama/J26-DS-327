// Verify readable plain-text answers with fictional content and no API calls.
import {test} from 'node:test';import assert from 'node:assert/strict';
import {createRequire} from 'node:module';import {readFileSync} from 'node:fs';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const module={exports:{}};
const js=ts.transpileModule(readFileSync(new URL('../src/pages/Assistant/AnswerBody.tsx',import.meta.url),'utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
new Function('require','module','exports',js)(require,module,module.exports);
const {AnswerBody}=module.exports;
test('meaning, review list and recorded score render as separate readable sections',()=>{
 const text='What this tells you:\nHistorical result.\n\nSuggested checks:\nGeneral review suggestions.\n• Check weather records.\n• Review operations.\n\nRecorded score:\n25.00';
 const html=renderToStaticMarkup(React.createElement(AnswerBody,{text}));
 assert.equal((html.match(/c3-answer-section/g)||[]).length,3);
 assert.equal((html.match(/<li>/g)||[]).length,2);
 assert.match(html,/<h4>What this tells you<\/h4>/);
 assert.match(html,/<p>25.00<\/p>/);assert.doesNotMatch(html,/•/);
});
test('Sinhala and Tamil text is retained without translation or raw markup',()=>{
 for(const text of ['ඊළඟට පරීක්ෂා කළ හැකි වාර්තා:\n• වාර්තා බලන්න.','அடுத்து பார்க்க வேண்டிய பதிவுகள்:\n• பதிவுகளைப் பார்க்கவும்.']){
  const html=renderToStaticMarkup(React.createElement(AnswerBody,{text}));
  assert.match(html,/<h4>/);assert.match(html,/<li>/);
 }
});
test('saved single-paragraph replies remain readable',()=>{
 const html=renderToStaticMarkup(React.createElement(AnswerBody,{text:'A saved answer with 25.00.'}));
 assert.match(html,/<p>A saved answer with 25.00.<\/p>/);assert.doesNotMatch(html,/<h4>/);
});
test('answer text cannot inject HTML or executable images',()=>{
 const html=renderToStaticMarkup(React.createElement(AnswerBody,{text:'Notes:\n• <img src=x onerror=alert(1)>\n\n<script>bad()</script>'}));
 assert.doesNotMatch(html,/<img|<script>/);assert.match(html,/&lt;img/);assert.match(html,/&lt;script/);
});
