/** Microphone audio stays local; playback selects only browser-reported local voices. */
import { useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import { localSpeechEndpoint, localVoice } from './voicePolicy';
import { t, type Language as ChatLanguage } from './i18n';

const MAX_BYTES = 6 * 1024 * 1024;
const languageLabels = { en: 'English', si: 'සිංහල', ta: 'தமிழ்' };
type Language = keyof typeof languageLabels;

export function VoiceInput({ disabled, onTranscript, onBusyChange, uiLanguage = 'en' }: { uiLanguage?: ChatLanguage; disabled: boolean; onTranscript: (text: string) => void; onBusyChange: (busy: boolean) => void }) {
  const [language, setLanguage] = useState<Language>(uiLanguage);
  useEffect(() => { setLanguage(uiLanguage); },[uiLanguage]);
  const [phase, setPhase] = useState<'idle' | 'checking' | 'recording' | 'transcribing'>('idle');
  const [notice, setNotice] = useState('');
  const [seconds, setSeconds] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setInterval>>();
  const limit = useRef<ReturnType<typeof setTimeout>>();
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const occupied = useRef(false);
  function release() {
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
    if (timer.current) clearInterval(timer.current);
    if (limit.current) clearTimeout(limit.current);
  }
  useEffect(() => () => {
    generation.current += 1; controller.current?.abort(); onBusyChange(false);
    if (recorder.current?.state === 'recording') { recorder.current.onstop = null; recorder.current.stop(); }
    release();
  }, []);
  function stop() {
    if (recorder.current?.state === 'recording') recorder.current.stop();
    release();
  }
  async function start() {
    if (occupied.current || disabled) return;
    if (!localSpeechEndpoint(api.defaults.baseURL, window.location.href)) {
      setNotice('Voice input requires a backend on this computer. Audio was not recorded or sent.'); return;
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setNotice('Microphone recording is unavailable here. Use Chrome or Edge on localhost.'); return;
    }
    occupied.current = true; onBusyChange(true); const token = ++generation.current;
    setPhase('checking'); setNotice('Checking local speech setup…');
    const abort = new AbortController(); controller.current = abort;
    try {
      const status = await api.get('/agent/voice/status', { signal: abort.signal, timeout: 10000 });
      if (token !== generation.current) return;
      if (status.data.ready !== true || status.data.cloud_processing !== false || status.data.provider !== 'local_whisper') {
        throw new Error('Local speech setup is incomplete. Install the C3 voice runtime and speech model first.');
      }
      setNotice('Allow microphone access to record a short question.');
      const microphone = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      if (token !== generation.current) { microphone.getTracks().forEach(track => track.stop()); return; }
      stream.current = microphone;
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('This browser has no supported audio recording format. Try Chrome or Edge.');
      const recording = new MediaRecorder(microphone, { mimeType }); recorder.current = recording;
      const chunks: Blob[] = []; let bytes = 0; let tooLarge = false; let recordingFailed = false;
      recording.ondataavailable = event => { if (event.data.size) { bytes += event.data.size; if (bytes > MAX_BYTES) { tooLarge = true; stop(); } else chunks.push(event.data); } };
      recording.onerror = () => { recordingFailed = true; setNotice('Microphone recording failed. Please try again.'); stop(); };
      recording.onstop = async () => {
        release(); if (token !== generation.current) return;
        setPhase('transcribing'); setNotice('Processing speech locally. The first recording may take longer while the model loads.');
        try {
          if (recordingFailed || tooLarge || !bytes) throw new Error('No usable audio was captured. Record a short question, up to 30 seconds.');
          const audio = new Blob(chunks, { type: mimeType });
          const { data } = await api.post('/agent/voice/transcribe', audio, {
            params: { language }, headers: { 'Content-Type': mimeType }, signal: abort.signal, timeout: 180000,
          });
          if (token !== generation.current) return;
          if (data.provider !== 'local_whisper' || data.cloud_processing !== false || typeof data.question_text !== 'string' || !data.question_text.trim()) throw new Error('No local speech transcript was returned.');
          onTranscript(data.question_text);
          setNotice(data.translated ? 'Speech converted to an English draft. Check names, dates and numbers before sending.' : 'Transcript added to your draft. Review it before sending.');
        } catch (error) {
          if (token === generation.current) {
            const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
            setNotice(typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Local transcription failed. Please try again.');
          }
        } finally { if (token === generation.current) { occupied.current = false; onBusyChange(false); setPhase('idle'); recorder.current = null; } }
      };
      recording.start(500); setSeconds(0); setPhase('recording'); setNotice('Recording on this device. Press Stop when finished.');
      const started = Date.now();
      timer.current = setInterval(() => setSeconds(Math.min(30, Math.floor((Date.now() - started) / 1000))), 250);
      limit.current = setTimeout(stop, 29500);
    } catch (error) {
      release();
      if (token === generation.current) {
        occupied.current = false; onBusyChange(false); setPhase('idle');
        setNotice(error instanceof DOMException && error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow access in your browser, then try again.' : error instanceof Error ? error.message : 'Voice input could not start.');
      }
    }
  }
  return <div className="c3-voice-input">
    <div className="c3-voice-row"><label>{t(uiLanguage,'Speech language')}<select value={language} disabled={phase !== 'idle'} onChange={event => setLanguage(event.target.value as Language)}>{Object.entries(languageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button type="button" className={`c3-mic${phase === 'recording' ? ' is-recording' : ''}`} disabled={disabled || (phase !== 'idle' && phase !== 'recording')} aria-pressed={phase === 'recording'} onClick={() => phase === 'recording' ? stop() : void start()}>
        <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.7"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>
        {phase === 'recording' ? `${t(uiLanguage,'Stop')} · ${seconds}s` : t(uiLanguage,phase === 'checking' ? 'Preparing…' : phase === 'transcribing' ? 'Transcribing…' : 'Speak question')}
      </button><small>{t(uiLanguage,'Up to 30 seconds · processed locally')}</small></div>
    {notice && <p className="c3-voice-notice" role="status">{t(uiLanguage,notice)}</p>}
    <p className="c3-voice-language-note">{t(uiLanguage,'Speech is transcribed in the selected input language. Answers use the chat language.')}</p>
  </div>;
}

export function ReadAloud({ text, language = 'en', uiLanguage = language }: { text: string; language?: ChatLanguage; uiLanguage?: ChatLanguage }) {
  const [available, setAvailable] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  useEffect(() => {
    if (!('speechSynthesis' in window)) return;
    const update = () => setAvailable(Boolean(localVoice(speechSynthesis.getVoices(),language)));
    update(); speechSynthesis.addEventListener('voiceschanged', update);
    return () => { speechSynthesis.removeEventListener('voiceschanged', update); speechSynthesis.cancel(); };
  }, [language]);
  function play() {
    if (speaking) { speechSynthesis.cancel(); setSpeaking(false); return; }
    const voice = localVoice(speechSynthesis.getVoices(),language);
    if (!voice) { setAvailable(false); return; }
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text); utterance.voice = voice; utterance.lang = voice.lang; utterance.rate = 0.95;
    utterance.onstart = () => setSpeaking(true); utterance.onend = utterance.onerror = () => setSpeaking(false);
    speechSynthesis.speak(utterance);
  }
  return <button type="button" className="c3-read-aloud" disabled={!available} onClick={play} aria-pressed={speaking}
    title={t(uiLanguage,available ? 'Uses an installed local voice' : 'A local voice for this language is required; remote voices are not used')}>
    {speaking ? `■ ${t(uiLanguage,'Stop reading')}` : available ? `◖ ${t(uiLanguage,'Read aloud')}` : t(uiLanguage,'Local voice unavailable')}
  </button>;
}
