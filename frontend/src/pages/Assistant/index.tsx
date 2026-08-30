import { useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import { useUser } from '../../context/UserContext';
import type { Role } from '../../types/api';
import { ContextChart } from './ContextChart';
import './Assistant.css';
import './VoiceInput.css';

type Language = 'en' | 'si' | 'ta';
type Tab = 'ask' | 'recent' | 'saved' | 'summary';
type Evidence = { source: string; label: string; freshness: string };
type Priority = { animal_id: string; priority?: string; reason?: string; expected_calving?: string };
type Answer = { answer: string; intent: string; confidence: number; recommendations: { action: string }[]; evidence: Evidence[]; priorityItems: Priority[]; visualization?: { type: string; title: string; data?: Record<string, string | number>[] } | null; conversationId?: string };
type Message = { id: string; question: string; request: string; response?: Answer; error?: string };

const prompts = [
  { en: 'Show my morning briefing.', si: 'මගේ උදෑසන සාරාංශය පෙන්වන්න.', ta: 'எனது காலை சுருக்கத்தைக் காட்டு.' },
  { en: 'Which cows need attention today?', si: 'අද අවධානය අවශ්‍ය ගවයන් කවුද?', ta: 'இன்று கவனம் தேவைப்படும் பசுக்கள் எவை?' },
  { en: 'How much milk did the farm produce this week compared with last week?', si: 'පසුගිය සතියට සාපේක්ෂව මේ සතියේ කිරි නිෂ්පාදනය කෙසේද?', ta: 'கடந்த வாரத்துடன் ஒப்பிடுகையில் இந்த வார பால் உற்பத்தி எவ்வளவு?' },
  { en: 'What happened to animal LK-2121 in the last 30 days?', si: 'පසුගිය දින 30 තුළ LK-2121 සතාට සිදු වූයේ කුමක්ද?', ta: 'கடந்த 30 நாட்களில் LK-2121 விலங்கிற்கு என்ன நடந்தது?' },
  { en: 'Which cows are expected to calve next month?', si: 'ලබන මාසයේ පැටවුන් බිහිකිරීමට නියමිත ගවයන් කවුද?', ta: 'அடுத்த மாதம் கன்று ஈன எதிர்பார்க்கப்படும் பசுக்கள் எவை?' },
  { en: 'Did the feed change we made two weeks ago improve production?', si: 'සති දෙකකට පෙර කළ ආහාර වෙනස නිෂ්පාදනය වැඩි කළාද?', ta: 'இரண்டு வாரங்களுக்கு முன் செய்த தீவன மாற்றம் உற்பத்தியை மேம்படுத்தியதா?' },
  { en: 'Summarize the farm today.', si: 'අද ගොවිපළ සාරාංශ කරන්න.', ta: 'இன்றைய பண்ணையைச் சுருக்கமாகக் கூறுங்கள்.' },
];

const copy = {
  en: { newChat: '+ New conversation', ask: 'Ask assistant', recent: 'Recent conversations', saved: 'Saved decisions', summary: 'Farm summary', greeting: 'Good morning. What would you like to know about your farm?', composer: 'Ask about your farm…', send: 'Send', working: 'Working…', you: 'You', evidence: 'Why this answer?', hide: 'Hide evidence', record: 'Record decision', actions: 'RECOMMENDED NEXT ACTIONS', chart: 'CHART', confidence: 'confidence', evidenceTitle: 'Evidence' },
  si: { newChat: '+ නව සංවාදය', ask: 'සහයකයාගෙන් අසන්න', recent: 'මෑත සංවාද', saved: 'සුරැකි තීරණ', summary: 'ගොවිපළ සාරාංශය', greeting: 'සුබ උදෑසනක්. ඔබේ ගොවිපළ ගැන දැනගැනීමට අවශ්‍ය කුමක්ද?', composer: 'ඔබේ ගොවිපළ ගැන අසන්න…', send: 'යවන්න', working: 'සකස් කරමින්…', you: 'ඔබ', evidence: 'මෙම පිළිතුර ඇයි?', hide: 'සාක්ෂි සඟවන්න', record: 'තීරණය සටහන් කරන්න', actions: 'නිර්දේශිත ඊළඟ ක්‍රියාමාර්ග', chart: 'ප්‍රස්තාරය', confidence: 'විශ්වාසය', evidenceTitle: 'සාක්ෂි' },
  ta: { newChat: '+ புதிய உரையாடல்', ask: 'உதவியாளரிடம் கேளுங்கள்', recent: 'சமீப உரையாடல்கள்', saved: 'சேமித்த முடிவுகள்', summary: 'பண்ணை சுருக்கம்', greeting: 'காலை வணக்கம். உங்கள் பண்ணையைப் பற்றி என்ன தெரிந்துகொள்ள விரும்புகிறீர்கள்?', composer: 'உங்கள் பண்ணையைப் பற்றி கேளுங்கள்…', send: 'அனுப்பு', working: 'செயலாக்குகிறது…', you: 'நீங்கள்', evidence: 'இந்த பதில் ஏன்?', hide: 'சான்றை மறை', record: 'முடிவை பதிவு செய்', actions: 'பரிந்துரைக்கப்பட்ட அடுத்த செயல்கள்', chart: 'வரைபடம்', confidence: 'நம்பிக்கை', evidenceTitle: 'சான்றுகள்' },
} as const;

const roles: Record<Role, string> = { farm_worker: 'Farm worker', veterinarian: 'Veterinarian', farm_manager: 'Farm manager', nldb_management: 'NLDB management' };
const speechLocales: Record<Language, string> = { en: 'en-LK', si: 'si-LK', ta: 'ta-LK' };
const voiceCopy = { en: { start: 'Start voice input', stop: 'Stop voice input', listening: 'Listening…', unavailable: 'Voice input is not supported in this browser. Try Chrome or Edge.', denied: 'Microphone access was denied. Please allow it and try again.' }, si: { start: 'හඬ ආදානය ආරම්භ කරන්න', stop: 'හඬ ආදානය නවත්වන්න', listening: 'අසමින් පවතී…', unavailable: 'මෙම බ්‍රවුසරයේ හඬ ආදානය සහාය නොදක්වයි. Chrome හෝ Edge භාවිතා කරන්න.', denied: 'මයික්‍රෆෝන අවසරය ප්‍රතික්ෂේප කර ඇත. අවසර දී නැවත උත්සාහ කරන්න.' }, ta: { start: 'குரல் உள்ளீட்டைத் தொடங்கு', stop: 'குரல் உள்ளீட்டை நிறுத்து', listening: 'கேட்கிறது…', unavailable: 'இந்த உலாவியில் குரல் உள்ளீடு ஆதரிக்கப்படவில்லை. Chrome அல்லது Edge பயன்படுத்தவும்.', denied: 'மைக்ரோஃபோன் அனுமதி மறுக்கப்பட்டது. அனுமதித்து மீண்டும் முயற்சிக்கவும்.' } } as const;
const titles: Record<Language, Record<string, string>> = {
  en: { morning_briefing: 'Morning briefing', herd_count: 'Herd snapshot', attention_animals: 'Animals needing attention', animal_history: 'Animal history', weekly_production_comparison: 'Production comparison', expected_calvings: 'Reproduction alert', feed_change_evaluation: 'Decision outcome', profit_overview: 'Farm profit overview', farm_summary: 'Farm summary' },
  si: { morning_briefing: 'උදෑසන සාරාංශය', herd_count: 'රංචු තොරතුරු', attention_animals: 'අවධානය අවශ්‍ය සතුන්', animal_history: 'සත්ව ඉතිහාසය', weekly_production_comparison: 'නිෂ්පාදන සංසන්දනය', expected_calvings: 'ප්‍රජනන දැනුම්දීම', feed_change_evaluation: 'තීරණ ප්‍රතිඵලය', profit_overview: 'ගොවිපළ ලාභය', farm_summary: 'ගොවිපළ සාරාංශය' },
  ta: { morning_briefing: 'காலை சுருக்கம்', herd_count: 'மந்தை நிலவரம்', attention_animals: 'கவனம் தேவைப்படும் விலங்குகள்', animal_history: 'விலங்கு வரலாறு', weekly_production_comparison: 'உற்பத்தி ஒப்பீடு', expected_calvings: 'இனப்பெருக்க எச்சரிக்கை', feed_change_evaluation: 'முடிவு விளைவு', profit_overview: 'பண்ணை லாபம்', farm_summary: 'பண்ணை சுருக்கம்' },
};

export default function Assistant() {
  const { role } = useUser();
  const [tab, setTab] = useState<Tab>('ask');
  const [language, setLanguage] = useState<Language>('en');
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState('');
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<any>(null);
  const t = copy[language];
  const voice = voiceCopy[language];

  useEffect(() => () => recognitionRef.current?.abort?.(), []);

  async function ask(request: string, selectedLanguage = language, existingId?: string, displayQuestion = request) {
    if (!request.trim() || loading) return;
    const pending = { id: existingId ?? crypto.randomUUID(), question: displayQuestion, request };
    if (!existingId) setMessages(items => [...items, pending]);
    setLoading(true);
    try {
      const { data } = await api.post<Answer>('/agent/query', { query: request, farm_id: 'FARM_01', role, language: selectedLanguage, conversation_id: conversationId });
      setConversationId(data.conversationId);
      setMessages(items => items.map(item => item.id === pending.id ? { ...item, response: data, error: undefined } : item));
    } catch {
      setMessages(items => items.map(item => item.id === pending.id ? { ...item, error: 'The farm-data service is unavailable. Check that the backend is running, then try again.' } : item));
    } finally { setLoading(false); }
  }
  function send(question = query) { setQuery(''); void ask(question); }
  function toggleVoice() {
    if (listening) { recognitionRef.current?.stop?.(); return; }
    const Recognition = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    if (!Recognition) { setVoiceNotice(voice.unavailable); return; }
    const recognition = new Recognition();
    recognitionRef.current = recognition;
    recognition.lang = speechLocales[language];
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onstart = () => { setVoiceNotice(''); setListening(true); };
    recognition.onresult = (event: any) => { const transcript = Array.from(event.results).map((result: any) => result[0].transcript).join(''); setQuery(transcript); };
    recognition.onerror = (event: any) => { setVoiceNotice(event.error === 'not-allowed' || event.error === 'service-not-allowed' ? voice.denied : voice.unavailable); };
    recognition.onend = () => { setListening(false); recognitionRef.current = null; inputRef.current?.focus(); };
    recognition.start();
  }
  function changeLanguage(next: Language) { setLanguage(next); const latest = messages[messages.length - 1]; const prompt = latest && prompts.find(item => item.en === latest.request); if (latest) void ask(latest.request, next, latest.id, prompt?.[next] ?? latest.question); }
  function newConversation() { setMessages([]); setConversationId(undefined); setQuery(''); setEvidenceId(null); setTab('ask'); window.setTimeout(() => inputRef.current?.focus(), 0); }

  return <div className="assistant-workspace">
    <header className="assistant-toolbar"><button className="new-conversation" onClick={newConversation}>{t.newChat}</button><div className="toolbar-context"><span>NLDB Ridiyagama Farm</span><span>{roles[role]}</span></div><div className="language-picker"><button className={language === 'si' ? 'active' : ''} onClick={() => changeLanguage('si')}>සිංහල</button><button className={language === 'en' ? 'active' : ''} onClick={() => changeLanguage('en')}>EN</button><button className={language === 'ta' ? 'active' : ''} onClick={() => changeLanguage('ta')}>தமிழ்</button></div></header>
    <nav className="assistant-tabs"><button className={tab === 'ask' ? 'active' : ''} onClick={() => setTab('ask')}>{t.ask}</button><button className={tab === 'recent' ? 'active' : ''} onClick={() => setTab('recent')}>{t.recent}</button><button className={tab === 'saved' ? 'active' : ''} onClick={() => setTab('saved')}>{t.saved}</button><button className={tab === 'summary' ? 'active' : ''} onClick={() => setTab('summary')}>{t.summary}</button></nav>
    <main className="assistant-content">{tab === 'ask' && <><section className="assistant-welcome"><span>DA</span><p>DAIRY INTELLIGENCE ASSISTANT</p><h1>{t.greeting}</h1><div className="prompt-grid">{prompts.map(prompt => <button key={prompt.en} onClick={() => void ask(prompt.en, language, undefined, prompt[language])}>{prompt[language]}<b>→</b></button>)}</div></section>{messages.map(message => <article className="chat-turn" key={message.id}><div className="user-message"><small>{t.you}</small>{message.question}</div>{!message.response && !message.error && <div className="thinking">{t.working}</div>}{message.error && <div className="response-error">{message.error}</div>}{message.response && <Response answer={message.response} language={language} t={t} expanded={evidenceId === message.id} onEvidence={() => setEvidenceId(evidenceId === message.id ? null : message.id)} />}</article>)}</>}{tab === 'recent' && <Empty title={t.recent} description={messages.length ? 'Select a previous question to continue the discussion.' : 'Your recent farm questions will appear here.'}>{messages.slice().reverse().map(message => <button className="history-item" key={message.id} onClick={() => { setQuery(message.question); setTab('ask'); }}>{message.question}<b>→</b></button>)}</Empty>}{tab === 'saved' && <Empty title={t.saved} description="Save a farm decision after reviewing a response to track its outcome over time." />}{tab === 'summary' && <Empty title={t.summary} description="Generate a concise view of today’s production, health, and priorities."><button className="summary-action" onClick={() => send('Summarize the farm today.')}>{t.summary}</button></Empty>}</main>
    <footer className="assistant-composer"><div><input ref={inputRef} value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => event.key === 'Enter' && send()} placeholder={t.composer}/><button className={`voice-button${listening ? ' listening' : ''}`} onClick={toggleVoice} aria-label={listening ? voice.stop : voice.start} title={listening ? voice.stop : voice.start} type="button"><MicrophoneIcon listening={listening}/><small>{listening ? voice.listening : ''}</small></button><button onClick={() => send()} disabled={!query.trim() || loading}>{loading ? t.working : t.send}</button></div>{voiceNotice && <p className="voice-notice" role="status">{voiceNotice}</p>}</footer>
  </div>;
}

function Empty({ title, description, children }: { title: string; description: string; children?: React.ReactNode }) { return <section className="empty-view"><span>DA</span><h1>{title}</h1><p>{description}</p>{children && <div>{children}</div>}</section>; }
function MicrophoneIcon({ listening }: { listening: boolean }) { return listening ? <svg aria-hidden="true" viewBox="0 0 24 24" className="voice-icon"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/><path d="M12 3v1M12 20v1M4 12h1M19 12h1M6.3 6.3l.7.7M17 17l.7.7M17.7 6.3l-.7.7M7 17l-.7.7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg> : <svg aria-hidden="true" viewBox="0 0 24 24" className="voice-icon"><rect x="8" y="3" width="8" height="12" rx="4" fill="none" stroke="currentColor" strokeWidth="1.8"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>; }
function Response({ answer, language, t, expanded, onEvidence }: { answer: Answer; language: Language; t: (typeof copy)[Language]; expanded: boolean; onEvidence: () => void }) { return <section className="assistant-response"><header><span>DA</span><div><p>DIGITAL AGRONOMIST</p><h2>{titles[language][answer.intent] ?? 'Farm guidance'}</h2></div><em>{Math.round(answer.confidence * 100)}% {t.confidence}</em></header><p className="answer-text">{answer.answer}</p>{answer.priorityItems.length > 0 && <div className="priority-items">{answer.priorityItems.map((item, index) => <div key={item.animal_id}><b>{index + 1}</b><span><strong>{item.animal_id}</strong><small>{item.reason ?? `Expected calving: ${item.expected_calving}`}</small></span><em>{item.priority ?? 'review'}</em></div>)}</div>}{answer.recommendations.length > 0 && <section className="recommendations"><p>{t.actions}</p><ol>{answer.recommendations.map(item => <li key={item.action}>{item.action}</li>)}</ol></section>}{answer.visualization && <ContextChart chart={answer.visualization} label={t.chart} language={language}/>}<footer><button onClick={onEvidence}>{expanded ? t.hide : t.evidence}</button><button>{t.record}</button></footer>{expanded && <div className="evidence"><h3>{t.evidenceTitle}</h3>{answer.evidence.map(item => <p key={item.label}><b>{item.label}</b><span>{item.source.replace('_', ' · ')} · {item.freshness}</span></p>)}</div>}</section>; }
