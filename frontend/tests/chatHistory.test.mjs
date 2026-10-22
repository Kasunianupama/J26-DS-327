// Synthetic local-storage checks; no browser profile, server or database is accessed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = readFileSync(new URL('../src/pages/Assistant/chatHistory.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const module = { exports: {} };
new Function('module', 'exports', js)(module, module.exports);
const { HISTORY_KEY, emptyHistory, newConversation, readHistory, saveHistory, decodeHistory } = module.exports;

function memory() {
  const values = new Map();
  return { values, writes: 0, getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { this.writes++; values.set(key, value); } };
}
function fixture() {
  const state = emptyHistory('synthetic-chat-1');
  const chat = state.conversations[0];
  chat.context = { topic: 'forecast', reference_date: '2020-01-01', awaiting: 'target_period', grain: 'weekly' };
  chat.reference = '2020-01-01'; chat.grain = 'weekly'; chat.datesOpen = true;
  chat.turns = [{ id: 'synthetic-turn-1', question: 'Show a weekly forecast', response: {
    status: 'needs_input', answer: 'Supply a target date.', context: { ...chat.context },
    provider: 'local_template', demo: false, cloud_processing: false,
    evidence: { source: 'synthetic-test', lower: null, forecast: 100 }, warnings: ['Synthetic fixture only.'],
  } }];
  return state;
}

test('refresh restores question, answer, evidence, missing values and follow-up context', () => {
  const storage = memory(); const state = fixture();
  assert.equal(saveHistory(storage, state), '');
  const loaded = readHistory(storage, emptyHistory('unused'));
  assert.equal(loaded.blocked, false);
  assert.deepEqual(loaded.store, state);
  assert.equal(loaded.store.conversations[0].context.awaiting, 'target_period');
  assert.equal(loaded.store.conversations[0].turns[0].response.evidence.lower, null);
});
test('separate conversations and active selection survive reload', () => {
  const state = fixture();
  state.conversations.push({ ...newConversation('synthetic-chat-2'), context: { topic: 'risk', reference_date: '2020-01-08' } });
  state.activeId = 'synthetic-chat-2';
  const loaded = decodeHistory(JSON.stringify(state));
  assert.equal(loaded.activeId, 'synthetic-chat-2');
  assert.equal(loaded.conversations[0].context.topic, 'forecast');
  assert.equal(loaded.conversations[1].context.topic, 'risk');
});
test('corrupt history is preserved and never silently overwritten on load', () => {
  const storage = memory(); storage.values.set(HISTORY_KEY, '{broken');
  const loaded = readHistory(storage, emptyHistory('fallback'));
  assert.equal(loaded.blocked, true); assert.match(loaded.notice, /could not be opened/);
  assert.equal(storage.values.get(HISTORY_KEY), '{broken'); assert.equal(storage.writes, 0);
});
test('unknown version, invalid selection and duplicate ids are rejected', () => {
  const state = fixture();
  assert.throws(() => decodeHistory(JSON.stringify({ ...state, version: 2 })));
  assert.throws(() => decodeHistory(JSON.stringify({ ...state, activeId: 'not-present' })));
  assert.throws(() => decodeHistory(JSON.stringify({ ...state, conversations: [state.conversations[0], state.conversations[0]] })));
});
test('non-local stored replies and invalid follow-up context are rejected', () => {
  const hosted = fixture(); hosted.conversations[0].turns[0].response.provider = 'hosted';
  assert.throws(() => decodeHistory(JSON.stringify(hosted)));
  const invalid = fixture(); invalid.conversations[0].context = { arbitrary_tool: 'unapproved' };
  assert.throws(() => decodeHistory(JSON.stringify(invalid)));
});
test('quota and disabled-storage failures return notices and do not mutate the in-memory conversation', () => {
  const state = fixture(); const original = structuredClone(state);
  assert.match(saveHistory({ setItem() { throw new Error('quota'); } }, state), /could not be saved/);
  assert.deepEqual(state, original);
  assert.equal(readHistory({ getItem() { throw new Error('disabled'); } }, emptyHistory('fallback')).blocked, true);
});
test('interrupted questions require resend and never gain a fabricated saved answer', () => {
  const state = fixture(); state.conversations[0].turns.push({ id: 'pending', question: '2020-01-08' });
  const pending = decodeHistory(JSON.stringify(state)).conversations[0].turns[1];
  assert.equal(pending.response, undefined); assert.match(pending.error, /interrupted/);
});
test('saving removal and a new conversation does not bring deleted messages back on refresh', () => {
  const storage = memory(); saveHistory(storage, fixture());
  const cleared = emptyHistory('replacement'); saveHistory(storage, cleared);
  const loaded = readHistory(storage, emptyHistory('unused')).store;
  assert.deepEqual(loaded, cleared); assert.equal(loaded.conversations[0].turns.length, 0);
});

test('validated local Qwen answers survive history reload with their generation provenance', () => {
  const state = fixture();
  const reply = state.conversations[0].turns[0].response;
  Object.assign(reply, { status: 'success', provider: 'local_qwen', answer_generation: 'grounded_milk_v1',
    generation_status: 'success', generation_model: 'qwen3:4b-instruct', answer: 'Fictional explanation only.' });
  assert.deepEqual(decodeHistory(JSON.stringify(state)), state);
  reply.generation_status = 'timeout';
  assert.throws(() => decodeHistory(JSON.stringify(state)));
  reply.generation_status = 'success'; reply.answer_generation = 'unknown';
  assert.throws(() => decodeHistory(JSON.stringify(state)));
});
