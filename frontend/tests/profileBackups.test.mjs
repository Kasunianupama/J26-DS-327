// Synthetic backups only; never read browser storage, exports, servers or databases.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const cache = new Map();
function load(name) {
  if (cache.has(name)) return cache.get(name);
  const js = ts.transpileModule(readFileSync(new URL(`../src/pages/Assistant/${name}.ts`, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const module = { exports: {} };
  new Function('require','module','exports',js)(path => load(path.replace('./','')),module,module.exports);
  cache.set(name,module.exports); return module.exports;
}
const { emptyHistory, saveHistory, readHistory, HISTORY_KEY } = load('chatHistory');
const { defaultProfiles, decodeProfiles, historyKey, makeBackup, decodeBackup, restoreBackup, mergeHistory, PROFILE_KEY } = load('profileBackups');
const profile = { id: 'synthetic-profile', label: 'Profile 2' };
function memory() {
  return { values:new Map(), writes:0, failOn:0,
    getItem(key) { return this.values.get(key) ?? null; },
    setItem(key,value) { this.writes++; if (this.writes === this.failOn) throw new Error('quota'); this.values.set(key,value); },
    removeItem(key) { this.values.delete(key); },
  };
}
function fixture(id='chat-1', question='Synthetic question') {
  const store = emptyHistory(id);
  store.conversations[0].context = { topic:'forecast', reference_date:'2020-01-01', awaiting:'target_period' };
  store.conversations[0].turns = [{ id:'turn-1',question,error:'Synthetic fixture only.' }];
  return store;
}

test('profiles and roles have separate storage and never fall back to legacy history', () => {
  const storage=memory();
  saveHistory(storage,fixture('legacy'),HISTORY_KEY);
  const manager=historyKey(profile.id,'farm_manager');
  saveHistory(storage,fixture('manager'),manager);
  const otherRole=readHistory(storage,emptyHistory('blank-worker'),historyKey(profile.id,'farm_worker'));
  const otherProfile=readHistory(storage,emptyHistory('blank-profile'),historyKey('another-profile','farm_manager'));
  assert.equal(otherRole.store.activeId,'blank-worker'); assert.equal(otherProfile.store.activeId,'blank-profile');
  assert.equal(readHistory(storage,emptyHistory('unused'),manager).store.activeId,'manager');
  assert.equal(JSON.parse(storage.getItem(HISTORY_KEY)).activeId,'legacy');
});
test('single-role backup uses the current memory snapshot and excludes other scopes', () => {
  const storage=memory();
  saveHistory(storage,fixture('other-role'),historyKey(profile.id,'veterinarian'));
  saveHistory(storage,fixture('other-profile'),historyKey('other-profile','farm_manager'));
  const backup=makeBackup(storage,profile,'farm_manager',fixture('current-memory'),false);
  assert.deepEqual(Object.keys(backup.roles),['farm_manager']);
  assert.equal(backup.roles.farm_manager.activeId,'current-memory');
  assert.equal(JSON.stringify(backup).includes('other-profile'),false);
});
test('whole-profile backup contains its saved roles but excludes other profiles', () => {
  const storage=memory();
  saveHistory(storage,fixture('vet-chat'),historyKey(profile.id,'veterinarian'));
  saveHistory(storage,fixture('foreign-chat'),historyKey('foreign','board_management'));
  const backup=decodeBackup(JSON.stringify(makeBackup(storage,profile,'farm_manager',fixture(),true)));
  assert.deepEqual(Object.keys(backup.roles).sort(),['farm_manager','veterinarian']);
  assert.equal(backup.roles.veterinarian.activeId,'vet-chat');
  assert.equal(JSON.stringify(backup).includes('foreign-chat'),false);
});
test('malformed saved role histories make whole-profile backup fail without silent omission', () => {
  const storage=memory(); storage.values.set(historyKey(profile.id,'veterinarian'),'{broken');
  assert.throws(()=>makeBackup(storage,profile,'farm_manager',fixture(),true));
});
test('restore can recreate a profile and retains dates and clarification context', () => {
  const storage=memory();
  const backup=makeBackup(storage,profile,'farm_manager',fixture(),false);
  const result=restoreBackup(storage,backup,defaultProfiles());
  assert.equal(result.added,1); assert.equal(result.profiles.activeId,profile.id);
  assert.equal(result.profiles.profiles.some(p=>p.id===profile.id),true);
  const restored=JSON.parse(storage.getItem(historyKey(profile.id,'farm_manager')));
  assert.equal(restored.conversations[0].context.awaiting,'target_period');
  assert.equal(restored.conversations[0].context.reference_date,'2020-01-01');
});
test('duplicate conversation IDs retain current answers, and unrelated scopes remain byte-identical', () => {
  const storage=memory();
  const current=fixture('same-chat','Keep current question');
  saveHistory(storage,current,historyKey(profile.id,'farm_manager'));
  saveHistory(storage,fixture('untouched-vet'),historyKey(profile.id,'veterinarian'));
  saveHistory(storage,fixture('untouched-foreign'),historyKey('other','farm_manager'));
  const vet=storage.getItem(historyKey(profile.id,'veterinarian'));
  const foreign=storage.getItem(historyKey('other','farm_manager'));
  const result=restoreBackup(storage,makeBackup(storage,profile,'farm_manager',fixture('same-chat','Older backup'),false),defaultProfiles());
  assert.equal(result.skipped,1); assert.equal(result.added,0);
  assert.deepEqual(JSON.parse(storage.getItem(historyKey(profile.id,'farm_manager'))),current);
  assert.equal(storage.getItem(historyKey(profile.id,'veterinarian')),vet);
  assert.equal(storage.getItem(historyKey('other','farm_manager')),foreign);
});
test('merging earlier chats is repeatable and retains the current conversation', () => {
  const original=fixture('original'); const current=fixture('current');
  const once=mergeHistory(current,original); const twice=mergeHistory(once.store,original);
  assert.equal(once.added,1); assert.equal(twice.added,0); assert.equal(twice.skipped,1);
  assert.equal(twice.store.activeId,'current'); assert.equal(twice.store.conversations.length,2);
});
test('invalid backup versions, roles, profile ids and history bodies are rejected before writes', () => {
  const storage=memory(); const valid=makeBackup(storage,profile,'farm_manager',fixture(),false);
  for (const invalid of [
    {...valid,version:2}, {...valid,roles:{admin:fixture()}},
    {...valid,profile:{id:'../bad',label:'Bad'}}, {...valid,roles:{farm_manager:{broken:true}}},
  ]) assert.throws(()=>restoreBackup(storage,invalid,defaultProfiles()));
  assert.equal(storage.writes,0);
});
test('partial storage failure rolls back all affected saved keys', () => {
  const storage=memory();
  storage.values.set(PROFILE_KEY,JSON.stringify(defaultProfiles()));
  saveHistory(storage,fixture('old-manager'),historyKey(profile.id,'farm_manager'));
  const snapshot=new Map(storage.values);
  const backup=makeBackup(storage,profile,'farm_manager',fixture('new-manager'),false);
  backup.roles.veterinarian=fixture('new-vet');
  storage.failOn=storage.writes+2;
  assert.throws(()=>restoreBackup(storage,backup,defaultProfiles()),/Previous saved histories were retained/);
  assert.deepEqual(storage.values,snapshot);
});
test('profile registry cannot select an unknown or duplicate profile id', () => {
  assert.throws(()=>decodeProfiles(JSON.stringify({...defaultProfiles(),activeId:'unknown'})));
  const registry=defaultProfiles(); registry.profiles.push(registry.profiles[0]);
  assert.throws(()=>decodeProfiles(JSON.stringify(registry)));
});
