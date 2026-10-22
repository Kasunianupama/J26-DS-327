/** Local C3 conversation with evidence and the Predictive Intelligence palette. */
import { useEffect, useRef, useState, type SetStateAction } from 'react';
import { api } from '../../services/api';
import '../PredictiveIntelligence/pfie.css';
import './LocalAssistant.css';
import { EvidencePanel } from './EvidencePanel';
import { AnswerBody } from './AnswerBody';
import { MilkReportView } from './MilkReportView';
import { EvidenceCautions } from './EvidenceCautions';
import { VoiceInput, ReadAloud } from './VoiceControls';

import type { Context, Reply, Turn, Conversation, HistoryStore } from './chatTypes';
import { HISTORY_KEY, emptyHistory, newConversation, readHistory, saveHistory, conversationTitle, decodeHistory } from './chatHistory';
import { mergeHistory } from './profileBackups';
import { t, message, LOCALES, type Language } from './i18n';

function AgronomistMark() {
  return <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" focusable="false">
    <path d="M25 21.5a11.5 11.5 0 1 0-6.3 4.7L12 29l.7-5.2" />
    <path d="M12.1 18.7c-3.1-6 2.7-10 10.6-10.2.1 8-4 13.4-10.6 10.2Z" />
    <path d="m9.4 22.2 9.5-9.5M14.7 16.9l.1-4M14.7 16.9l4.1-.1" />
  </svg>;
}

const suggestions = [
  { icon: '↗', title: 'Milk production', question: 'Compare the latest recorded milk week with the previous week.', hint: 'Totals, coverage and weekly change' },
  { icon: '⌂', title: 'Herd snapshot', question: 'Show the latest recorded herd summary.', hint: 'Recorded herd and milking counts' },
  { icon: '☀', title: 'Weather context', question: 'Summarize the historical weather and THI.', hint: 'Recorded heat conditions and coverage' },
  { icon: '◷', title: 'Milk outlook', question: 'Show a daily milk forecast.', hint: 'Explore a stored model forecast' },
  { icon: '◇', title: 'Historical risk', question: 'Show a historical risk assessment.', hint: 'Research scores with their limitations' },
  { icon: '⇄', title: 'What-if scenario', question: 'Run a THI or milking-frequency what-if.', hint: 'Ask a what-if question in chat' },
];


type Props = { storageKey?: string; scopeLabel?: string; onBackup?: (history: HistoryStore, wholeProfile: boolean) => void; onRestore?: () => void; backupDisabled?: boolean; onLanguageChange?: (language: Language) => void };
export default function LocalAssistant({ storageKey = HISTORY_KEY, scopeLabel = 'This browser', onBackup, onRestore, backupDisabled = false, onLanguageChange }: Props) {
  const [initial] = useState(() => {
    try { return readHistory(window.localStorage, emptyHistory(), storageKey); }
    catch { return { store: emptyHistory(), blocked: true, notice: 'Browser storage is unavailable. Chats will remain in memory until you leave this page.' }; }
  });
  const [history, setHistory] = useState(initial.store);
  const [storageNotice, setStorageNotice] = useState(initial.notice);
  const [storageBlocked, setStorageBlocked] = useState(initial.blocked);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const current = history.conversations.find(item => item.id === history.activeId)!;
  const { turns, context, datesOpen, reference, target, grain } = current;
  const language: Language = current.language ?? 'en';
  useEffect(() => { onLanguageChange?.(language); }, [language, onLanguageChange]);
  function updateCurrent(update: (conversation: Conversation) => Conversation) {
    setHistory(previous => ({ ...previous, conversations: previous.conversations.map(item =>
      item.id === previous.activeId ? { ...update(item), updatedAt: new Date().toISOString() } : item) }));
  }
  function changeField<K extends keyof Conversation>(key: K, value: SetStateAction<Conversation[K]>) {
    updateCurrent(item => ({ ...item, [key]: typeof value === 'function'
      ? (value as (previous: Conversation[K]) => Conversation[K])(item[key]) : value }));
  }
  const setTurns = (value: SetStateAction<Turn[]>) => changeField('turns', value);
  const setContext = (value: SetStateAction<Context>) => changeField('context', value);
  const setDatesOpen = (value: boolean) => changeField('datesOpen', value);
  const setReference = (value: string) => changeField('reference', value);
  const setTarget = (value: string) => changeField('target', value);
  const setGrain = (value: string) => changeField('grain', value);
  useEffect(() => {
    if (storageBlocked) return;
    try { setStorageNotice(saveHistory(window.localStorage, history, storageKey)); }
    catch { setStorageNotice('Browser storage is unavailable. Chats are currently held in memory only.'); }
  }, [history, storageBlocked, storageKey]);
  useEffect(() => {
    function changedElsewhere(event: StorageEvent) {
      if (event.key === storageKey || event.key === null) {
        setStorageBlocked(true);
        setStorageNotice('Saved history changed in another tab. Reload this page before saving more changes; your current conversation remains in memory.');
      }
    }
    window.addEventListener('storage', changedElsewhere);
    return () => window.removeEventListener('storage', changedElsewhere);
  }, []);
  const [legacyAvailable, setLegacyAvailable] = useState(() => { try { return storageKey !== HISTORY_KEY && localStorage.getItem(HISTORY_KEY) !== null; } catch { return false; } });
  const [historyNotice, setHistoryNotice] = useState('');
  const sequence = useRef(0);
  const busy = useRef(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => { if (turns.length) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [turns, loading]);
  useEffect(() => () => { sequence.current += 1; }, []);

  async function ask(question = query) {
    if (!question.trim() || busy.current || voiceBusy) return;
    if (question.length > 1500) { setHistoryNotice('Please shorten the question to 1,500 characters before sending.'); return; }
    const request = ++sequence.current;
    const id = crypto.randomUUID();
    busy.current = true; setLoading(true); setQuery('');
    setTurns(items => [...items, { id, question }]);
    try {
      const { data } = await api.post<Reply>('/agent/chat', {
        query: question, language, context, reference_date: reference || null,
        target_period: target || null, grain: datesOpen ? grain : undefined,
      }, { timeout: 60000 });
      if (request !== sequence.current) return;
      if (data.demo !== false || data.cloud_processing !== false || !['local_template', 'local_qwen'].includes(data.provider)
          || (data.provider === 'local_qwen' && (data.status !== 'success' || data.answer_generation !== 'grounded_milk_v1' || data.generation_status !== 'success'))) throw new Error('Unexpected provider');
      setContext(data.context);
      if (data.context.grain) setGrain(data.context.grain);
      setTurns(items => items.map(item => item.id === id ? { ...item, response: data } : item));
    } catch {
      if (request === sequence.current) setTurns(items => items.map(item => item.id === id ? {
        ...item, error: 'I could not reach the local assistant. Check the backend and try sending your question again.',
      } : item));
    } finally {
      if (request === sequence.current) { busy.current = false; setLoading(false); input.current?.focus(); }
    }
  }

  function stopCurrentRequest() {
    if (busy.current) setTurns(items => items.map(turn => turn.response || turn.error ? turn : {
      ...turn, error: 'This request was interrupted when you left the conversation. Please send the question again.',
    }));
    sequence.current += 1; busy.current = false; setLoading(false); setQuery('');
  }
  function reset() {
    stopCurrentRequest();
    if (current.turns.length || voiceBusy) {
      const conversation = { ...newConversation(), language };
      setHistory(previous => ({ ...previous, activeId: conversation.id,
        conversations: [...previous.conversations.filter(item => item.turns.length), conversation] }));
    } else {
      updateCurrent(item => ({ ...newConversation(item.id), language }));
    }
    input.current?.focus();
  }
  function openConversation(id: string) {
    stopCurrentRequest();
    setHistory(previous => ({ ...previous, activeId: id }));
    input.current?.focus();
  }
  function deleteConversation(id: string) {
    if (!window.confirm(t(language,'Delete this saved conversation from this browser?'))) return;
    if (id === history.activeId) stopCurrentRequest();
    setHistory(previous => {
      const remaining = previous.conversations.filter(item => item.id !== id);
      if (!remaining.length) return emptyHistory();
      return { ...previous, conversations: remaining,
        activeId: previous.activeId === id ? remaining[remaining.length - 1].id : previous.activeId };
    });
  }
  function clearHistory() {
    if (!window.confirm(message(language,'Clear chats for {scope} only? This also clears its open conversation.',{scope:scopeLabel}))) return;
    stopCurrentRequest();
    setHistory(emptyHistory()); setStorageBlocked(false); setStorageNotice('');
  }
  function retrySave() {
    try { setStorageNotice(saveHistory(window.localStorage, history, storageKey)); }
    catch { setStorageNotice('Browser storage remains unavailable. Chats are held in memory only.'); }
  }
  function importPreviousChats() {
    if (!window.confirm(message(language,'Copy the earlier, unassigned chat history into {scope}? Existing chats will be kept and the original history will remain available.',{scope:scopeLabel}))) return;
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      if (raw === null) { setLegacyAvailable(false); return; }
      const merged = mergeHistory(history, decodeHistory(raw));
      const error = saveHistory(localStorage, merged.store, storageKey);
      if (error) { setHistoryNotice(error); return; }
      stopCurrentRequest(); setHistory(merged.store); setLegacyAvailable(false);
      setHistoryNotice(message(language,'Imported {added} earlier chats. Kept {skipped} chats already present. The original history was preserved.',{added:merged.added,skipped:merged.skipped}));
    } catch { setHistoryNotice('Earlier history could not be imported. Its original saved copy has not been changed.'); }
  }
  const saved = history.conversations.filter(item => item.turns.length)
    .slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  return <div className="pfie c3-chat" lang={language}>
    <header className="pfie-head"><div className="pfie-bar c3-bar">
      <div className="c3-identity"><span className="c3-mark" aria-hidden="true"><AgronomistMark /></span><div><h1>{t(language,'Digital Agronomist')}</h1><p>{t(language,'Farm X · Your farm, explained')}</p></div></div>
      <div className="c3-language-picker" role="group" aria-label={t(language,'Answer language')}>{(['en','si','ta'] as const).map(value => <button key={value} disabled={loading || voiceBusy} aria-pressed={language === value} onClick={() => changeField('language',value)}>{({en:'English',si:'සිංහල',ta:'தமிழ்'})[value]}</button>)}</div>
      <span className="c3-local"><i />{t(language,'Local processing')}</span>
      <button className="c3-history-toggle" onClick={() => setHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="c3-history">◷ {t(language,'History')}</button>
      <button className="c3-new" onClick={reset}>＋ {t(language,'New conversation')}</button>
    </div></header>
    {historyNotice && <p className="c3-storage-notice" role="status">{t(language,historyNotice)}</p>}
    {storageNotice && <div className="c3-storage-notice" role="status">{t(language,storageNotice)}{!storageBlocked && <button onClick={retrySave}>{t(language,'Retry saving')}</button>}</div>}
    <div className={`c3-shell${historyOpen ? '' : ' c3-history-hidden'}`}>
      {historyOpen && <aside id="c3-history" className="c3-guide c3-history" aria-label="Chat history">
        <div className="c3-history-heading"><div><span className="c3-eyebrow">{t(language,"YOUR CONVERSATIONS")}</span><h2>{t(language,"Chat history")}</h2></div><span>{saved.length}</span></div>
        <p className="c3-history-description">{scopeLabel}<br />{t(language,"Reopen a chat and continue where you left off.")}</p>
        {!saved.length ? <div className="c3-history-empty"><span aria-hidden="true">◷</span><strong>{t(language,"Your chats will appear here")}</strong><p>{t(language,"Start a conversation. It will be saved automatically in this browser.")}</p></div>
          : <ol className="c3-history-list">{saved.map(item => <li key={item.id} className={item.id === history.activeId ? 'is-active' : ''}>
            <button className="c3-history-open" aria-current={item.id === history.activeId ? 'true' : undefined} onClick={() => openConversation(item.id)} title={conversationTitle(item)}>
              <strong>{conversationTitle(item)}</strong><small>{item.turns.length} {t(language,item.turns.length === 1 ? 'question' : 'questions')} · {new Date(item.updatedAt).toLocaleDateString(LOCALES[language], { day: 'numeric', month: 'short' })}</small>
            </button><button className="c3-history-delete" aria-label={`${t(language,'Delete conversation')}: ${conversationTitle(item)}`} onClick={() => deleteConversation(item.id)}>×</button>
          </li>)}</ol>}
        <button className="c3-history-clear" onClick={clearHistory} disabled={!saved.length && !storageBlocked}>{t(language,"Clear saved chats")}</button>
        <div className="c3-backup-actions" aria-label="Chat backup and restore">
          {onBackup && <><button disabled={loading || backupDisabled} onClick={() => onBackup(history, false)}>↓ {t(language,'Back up this role')}</button><button disabled={loading || backupDisabled} onClick={() => onBackup(history, true)}>↓ {t(language,'Back up whole profile')}</button></>}
          {onRestore && <button disabled={loading || backupDisabled} onClick={() => {
            try { const error = saveHistory(localStorage, history, storageKey); if (error) { setHistoryNotice(error); return; } }
            catch { setHistoryNotice('Save the current conversation before restoring a backup.'); return; }
            onRestore();
          }}>↥ {t(language,'Restore backup')}</button>}
          {legacyAvailable && <button disabled={loading || storageBlocked} onClick={importPreviousChats}>{t(language,"Import earlier unassigned chats")}</button>}
        </div>
        <p className="c3-history-local">{t(language,"Saved for this profile and role in this browser only. Backup files contain conversations and evidence; keep them on a trusted device. These profiles do not restrict who can access chats.")}</p>
      </aside>}
      <section className="c3-conversation" aria-label="Farm conversation">
        {!turns.length ? <div className="c3-welcome"><span className="c3-welcome-icon" aria-hidden="true"><AgronomistMark /></span><span className="c3-eyebrow">{t(language,"LET’S LOOK AT YOUR FARM")}</span><h2>{t(language,'What would you like to understand?')}</h2><p>{t(language,"Start with a question, or explore one of these topics.")}</p>
          <div className="c3-suggestions">{suggestions.map(item => <button key={item.title} onClick={() => void ask(t(language,item.question))}><span aria-hidden="true">{item.icon}</span><strong>{t(language,item.title)}</strong><small>{t(language,item.hint)}</small><b aria-hidden="true">↗</b></button>)}</div>
        </div> : <div className="c3-turns" aria-live="polite" aria-busy={loading}>{turns.map(turn => <article className="c3-turn" key={turn.id}>
          <div className="c3-question"><span>{t(language,'You')}</span><p>{turn.question}</p></div>
          {turn.error && <div className="c3-error" role="alert">{t(language,turn.error)}</div>}
          {turn.response && <section className="c3-answer"><header><span className="c3-answer-mark" aria-hidden="true"><AgronomistMark /></span><div><small>{t(language,'Digital Agronomist')}</small><h3>{t(language,turn.response.title ?? (turn.response.status === 'needs_input' ? 'One more detail' : 'Let’s check that'))}</h3></div><span className="c3-answer-label">{t(language,turn.response.status === 'success' ? (turn.response.evidence?.kind === 'c2_live_simulation' ? 'Model what-if' : 'From your records') : turn.response.status === 'needs_input' ? 'Clarification' : 'Information')}</span></header>
            {turn.response.evidence && <MilkReportView evidence={turn.response.evidence} language={turn.response.language ?? language} />}
            <div className="c3-answer-body" lang={turn.response.language ?? 'en'}><AnswerBody text={turn.response.answer} /></div>
            <ReadAloud text={turn.response.answer} language={turn.response.language ?? 'en'} uiLanguage={language} />
            <EvidenceCautions reply={turn.response} language={language} />
            {turn.response.evidence && <EvidencePanel evidence={turn.response.evidence} language={language} />}
          </section>}
        </article>)}{loading && <p className="c3-thinking" role="status"><span />{t(language,"Checking your local records…")}</p>}<div ref={bottom} /></div>}
        <footer className="c3-composer"><p className="c3-language-note">{t(language,'New replies use the selected language. Saved replies keep their original language.')}</p><form onSubmit={event => { event.preventDefault(); void ask(); }}>
          <label className="c3-sr" htmlFor="c3-question">{t(language,"Ask about your farm")}</label>
          <textarea id="c3-question" ref={input} value={query} maxLength={1500} rows={2} placeholder={t(language,context.awaiting?.startsWith('simulation_') ? 'Reply with the missing cow or scenario detail…' : context.awaiting ? 'Reply with a date in YYYY-MM-DD…' : 'Ask about milk, your herd, forecasts or historical risk…')} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(); } }} />
          {query.length > 1500 && <p className="c3-voice-notice" role="alert">{t(language,"Your draft is too long. Shorten it to 1,500 characters before sending.")}</p>}
          <VoiceInput key={current.id} uiLanguage={language} disabled={loading} onBusyChange={setVoiceBusy} onTranscript={text => setQuery(previous => { const draft = previous.trim() ? `${previous.trim()} ${text}` : text; return draft; })} />
          <div className="c3-compose-actions"><button className="c3-dates-toggle" type="button" aria-expanded={datesOpen} onClick={() => setDatesOpen(!datesOpen)}>◷ {t(language,datesOpen ? 'Hide dates' : 'Add dates')}</button><span>{t(language,'Local factual answers')}</span><button type="submit" className="c3-send" disabled={loading || voiceBusy || !query.trim() || query.length > 1500}>{t(language,loading ? 'Checking…' : 'Send question')} <b aria-hidden="true">↑</b></button></div>
          {datesOpen && <div className="c3-date-controls"><details className="c3-date-advanced"><summary>{t(language,"Review older records")}</summary><label>{t(language,"Past day to review (optional)")}<input type="date" value={reference} onChange={event => { setReference(event.target.value); setContext(current => ({ ...current, reference_date: null })); }} /></label><small>{t(language,"Leave blank to select a forecast automatically. For historical risk, choose the past day you want to review.")}</small></details><label>{t(language,"Forecast date")}<input type="date" value={target} onChange={event => { setTarget(event.target.value); setContext(current => ({ ...current, target_period: null })); }} /></label><label>{t(language,"Forecast period")}<select value={grain} onChange={event => setGrain(event.target.value)}><option value="daily">{t(language,"Daily")}</option><option value="weekly">{t(language,"Weekly")}</option><option value="monthly">{t(language,"Monthly")}</option></select></label><button type="button" onClick={() => { setReference(''); setTarget(''); setContext(current => ({ ...current, reference_date: null, target_period: null, awaiting: null })); }}>{t(language,"Clear dates")}</button></div>}
        </form><p className="c3-composer-foot">{t(language,"Answers use recorded evidence. Forecasts are estimates; research assessments are not live alerts.")}</p></footer>
      </section>
    </div>
  </div>;
}
