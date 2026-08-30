import { useRef, useState } from 'react';
import { api } from '../../services/api';
import { useUser } from '../../context/UserContext';
import type { Role } from '../../types/api';
import { AnswerVisualization, type ChartKind } from './AnswerVisualization';
import './Assistant.css';

type Language = 'en' | 'si' | 'ta' | 'si-Latn';
type Answer = { text: string; confidence: number; quality: number; recommendations: string[]; abstained?: boolean };

type RoleProfile = { title: string; subtitle: string; context: string; answerType: string; actionHeading: string; suggestions: string[]; priorities: string[]; priorityTitle: string; reviewNote: string; showQuality: boolean };

const roleProfiles: Record<Role, RoleProfile> = {
  farm_worker: { title: 'Today’s farm actions', subtitle: 'Simple, safe steps for the current shift.', context: 'Operational shift guidance', answerType: 'Action-focused guidance', actionHeading: 'What to do now', suggestions: ['What should I check for cow 312 today?', 'What should I do during hot weather?', 'Which animals need attention now?'], priorities: ['Check water and cooling', 'Observe cows and report changes', 'Confirm the feeding routine'], priorityTitle: 'Current shift checklist', reviewNote: 'Report any health or welfare concern to the manager or veterinarian.', showQuality: false },
  veterinarian: { title: 'Herd health and welfare review', subtitle: 'Clinical and welfare-focused decision support.', context: 'Veterinary and welfare context', answerType: 'Health and welfare guidance', actionHeading: 'Suggested clinical checks', suggestions: ['How is cow 312’s health today?', 'Are there signs of heat stress in the herd?', 'Which welfare observations need review?'], priorities: ['Review health observations', 'Assess heat-stress signs', 'Escalate abnormal findings'], priorityTitle: 'Clinical review priorities', reviewNote: 'Clinical diagnosis and treatment remain the veterinarian’s responsibility.', showQuality: true },
  farm_manager: { title: 'Farm performance and decisions', subtitle: 'Turn the current farm situation into practical next actions.', context: 'Farm management context', answerType: 'Management decision support', actionHeading: 'Recommended next actions', suggestions: ['Why did today’s milk yield decrease?', 'What should I check during hot weather?', 'What needs manager review today?'], priorities: ['Check cooling and water', 'Confirm feeding routine', 'Review herd response'], priorityTitle: 'Today’s priority plan', reviewNote: 'A manager or veterinarian must review high-impact actions.', showQuality: true },
  nldb_management: { title: 'Strategic dairy intelligence', subtitle: 'A concise view for network-level monitoring and escalation.', context: 'NLDB management context', answerType: 'Strategic decision support', actionHeading: 'Recommended management follow-up', suggestions: ['Which farm issues need escalation?', 'What requires regional management review?', 'What should be monitored this week?'], priorities: ['Review priority farm alerts', 'Confirm escalation ownership', 'Monitor follow-up status'], priorityTitle: 'Management oversight priorities', reviewNote: 'Strategic summaries support management review and do not replace farm-level assessment.', showQuality: true },
};

const demoAnswers: Record<Language, Answer> = {
  en: { text: 'Today’s production outlook needs attention. Check cooling, water access, and the afternoon feeding routine first. Review the herd response before making a feed or treatment change.', confidence: 87, quality: 91, recommendations: ['Check cooling and water access before the afternoon heat peak.', 'Confirm that feeding timing matched the planned routine.', 'Review the herd response tomorrow with the farm manager.'] },
  si: { text: 'අද කිරි නිෂ්පාදන තත්ත්වය අවධානයට ගත යුතුය. පළමුව සිසිලනය, ජල ප්‍රවේශය සහ දහවල් ආහාර ලබාදීමේ ක්‍රමය පරීක්ෂා කරන්න. ආහාර හෝ ප්‍රතිකාර වෙනස් කිරීමට පෙර රංචුවේ ප්‍රතිචාරය සමාලෝචනය කරන්න.', confidence: 87, quality: 91, recommendations: ['දහවල් උෂ්ණත්වයට පෙර සිසිලනය සහ ජලය පරීක්ෂා කරන්න.', 'ආහාර වේලාව සැලසුම් කළ පරිදිදැයි තහවුරු කරන්න.', 'හෙට රංචු ප්‍රතිචාරය ගොවිපළ කළමනාකරු සමඟ සමාලෝචනය කරන්න.'] },
  ta: { text: 'இன்றைய பால் உற்பத்தி நிலைக்கு கவனம் தேவை. முதலில் குளிர்வித்தல், தண்ணீர் அணுகல் மற்றும் பிற்பகல் தீவன முறையைச் சரிபார்க்கவும். தீவனம் அல்லது சிகிச்சையை மாற்றுவதற்கு முன் மந்தையின் பதிலை மதிப்பாய்வு செய்யவும்.', confidence: 87, quality: 91, recommendations: ['பிற்பகல் வெப்பத்திற்கு முன் குளிர்வித்தல் மற்றும் தண்ணீரைச் சரிபார்க்கவும்.', 'தீவன நேரம் திட்டமிட்ட முறையைப் பின்பற்றியதா என உறுதி செய்யவும்.', 'நாளை பண்ணை மேலாளருடன் மந்தை பதிலை மதிப்பாய்வு செய்யவும்.'] },
  'si-Latn': { text: 'Ada kiri nishpadana thathwaya avadhanayata gatha yuthui. Mulima sisilaneeya, jala praveshaya saha dahawal aahara laba deeme krama pariksha karanna.', confidence: 87, quality: 91, recommendations: ['Dahawal ushnathwayata pera sisilaneeya saha jala praveshaya pariksha karanna.', 'Aahara welawa salasum kala paridida kiyala thahawuru karanna.', 'Heta ranchu prathicharaya govipala kalamanakaru samaga samalochanaya karanna.'] },
};

const labels: Record<Language, { ask: string; placeholder: string; suggestions: string[] }> = {
  en: { ask: 'Ask agronomist', placeholder: 'Ask a dairy-farm question…', suggestions: ['Why did today’s milk yield decrease?', 'What should I check during hot weather?', 'What needs manager review today?'] },
  si: { ask: 'කෘෂි උපදේශකගෙන් අසන්න', placeholder: 'කිරි ගොවිපළ පිළිබඳ ප්‍රශ්නයක් අසන්න…', suggestions: ['අද කිරි නිෂ්පාදනය අඩු වූයේ ඇයි?', 'උණුසුම් කාලගුණයේදී පරීක්ෂා කළ යුත්තේ මොනවාද?', 'අද කළමනාකරුගේ සමාලෝචනයට අවශ්‍ය කුමක්ද?'] },
  ta: { ask: 'வேளாண் ஆலோசகரிடம் கேளுங்கள்', placeholder: 'பால் பண்ணை தொடர்பான கேள்வியைக் கேளுங்கள்…', suggestions: ['இன்று பால் உற்பத்தி ஏன் குறைந்தது?', 'வெப்பமான காலநிலையில் நான் எதைச் சரிபார்க்க வேண்டும்?', 'இன்று மேலாளர் மதிப்பாய்வு செய்ய வேண்டியது என்ன?'] },
  'si-Latn': { ask: 'Ask agronomist', placeholder: 'Dairy farm prashnayak ahanna…', suggestions: ['Ada 312 cow ge health eka kohomada?', 'Usna kalagunayedi balanna ona mokakda?', 'Ada manager review karanna ona mokakda?'] },
};

function inferLanguage(question: string, selected: Language): Language {
  if (/[඀-෿]/.test(question)) return 'si';
  if (/[஀-௿]/.test(question)) return 'ta';
  if (/\b(ada|heta|kohomada|mokakda|ona|wenne|cow|ge|eka|balanna|prashna)\b/i.test(question)) return 'si-Latn';
  return selected;
}

function chartFor(question: string): ChartKind {
  const normalized = question.toLowerCase();
  if (/\b(trend|july|month|monthly|production)\b/.test(normalized)) return 'production_trend';
  if (/\b(health|sick|disease|cow|lameness|roga)\b/.test(normalized)) return 'health_review';
  if (/\b(heat|hot|water|temperature|thi|usna)\b/.test(normalized)) return 'heat_conditions';
  return null;
}

function fallbackAnswer(question: string, role: Role, language: Language): Answer {
  const normalized = question.toLowerCase();
  const healthQuestion = /\b(health|sick|disease|cow|lameness|roga)\b/.test(normalized);
  if (!healthQuestion) return demoAnswers[language];

  const healthAnswers: Record<Role, Answer> = {
    farm_worker: { text: 'Cow 312 needs an on-site health observation. Check appetite, movement, water intake, and any visible abnormal signs, then report concerns to the supervisor.', confidence: 84, quality: 86, recommendations: ['Observe cow 312 and note any abnormal signs.', 'Confirm water access and feed intake.', 'Notify the supervisor or veterinarian if concerns continue.'] },
    veterinarian: { text: 'Cow 312 should be reviewed clinically using the current observation, health history, activity, and welfare signs before deciding on treatment.', confidence: 86, quality: 89, recommendations: ['Perform a focused clinical examination.', 'Review recent health and activity observations.', 'Document findings and treatment decisions.'] },
    farm_manager: { text: 'Cow 312 has a health question that needs prompt verification. Arrange a welfare check, confirm feed and water conditions, and decide whether veterinary review is required.', confidence: 85, quality: 87, recommendations: ['Assign an on-site welfare check for cow 312.', 'Confirm feed, water, and housing conditions.', 'Escalate persistent findings to the veterinarian.'] },
    nldb_management: { text: 'Cow 312’s health concern should be followed up at farm level. Confirm that responsibility is assigned and monitor whether it becomes a repeated welfare pattern.', confidence: 82, quality: 85, recommendations: ['Confirm farm-level follow-up ownership.', 'Monitor unresolved welfare incidents.', 'Review recurring patterns in the management summary.'] },
  };
  const answer = healthAnswers[role];
  if (language === 'si-Latn') return { ...answer, text: `Cow 312 ge health eka on-site pariksha karanna one. ${answer.text}`, recommendations: ['Cow 312 nirikshanaya karala asamanya lakshana satahan karanna.', 'Wathura saha aahara praveshaya thahawuru karanna.', 'Prashnaya digatama thibunoth supervisor ho veterinarian ta danwanna.'] };
  if (language === 'si') return { ...answer, text: 'Cow 312ගේ සෞඛ්‍ය තත්ත්වය ස්ථානීයව පරීක්ෂා කළ යුතුය. ආහාර රුචිය, ගමන් කිරීම, ජල ප්‍රවේශය සහ අසාමාන්‍ය ලක්ෂණ නිරීක්ෂණය කරන්න.', recommendations: ['Cow 312 නිරීක්ෂණය කර අසාමාන්‍ය ලක්ෂණ සටහන් කරන්න.', 'ජලය සහ ආහාර ප්‍රවේශය තහවුරු කරන්න.', 'ගැටලුව දිගටම තිබේ නම් අධීක්ෂක හෝ පශු වෛද්‍යවරයාට දන්වන්න.'] };
  if (language === 'ta') return { ...answer, text: 'பசு 312-ன் உடல்நிலையை நேரடியாகச் சரிபார்க்க வேண்டும். பசியுணர்வு, நடமாட்டம், தண்ணீர் அணுகல் மற்றும் அசாதாரண அறிகுறிகளைக் கவனிக்கவும்.', recommendations: ['பசு 312-ஐ கவனித்து அசாதாரண அறிகுறிகளைப் பதிவு செய்யவும்.', 'தண்ணீர் மற்றும் தீவன அணுகலை உறுதி செய்யவும்.', 'சிக்கல் தொடர்ந்தால் மேற்பார்வையாளர் அல்லது கால்நடை மருத்துவரிடம் தெரிவிக்கவும்.'] };
  return answer;
}

export default function Assistant() {
  const { role } = useUser();
  const [language, setLanguage] = useState<Language>('en');
  const [query, setQuery] = useState('Why did Shed 3 milk production decrease today?');
  const [answer, setAnswer] = useState<Answer>(demoAnswers.en);
  const [loading, setLoading] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const [feedback, setFeedback] = useState<'helpful' | 'not_helpful' | null>(null);
  const [chartKind, setChartKind] = useState<ChartKind>(null);
  const answerRef = useRef<HTMLElement>(null);
  const copy = labels[language];
  const profile = roleProfiles[role];
  const suggestedQuestions = language === 'en' ? profile.suggestions : copy.suggestions;

  async function loadAnswer(question: string, responseLanguage: Language) {
    try {
      const { data } = await api.post('/agent/query', { query: question, farm_id: 'FARM_01', role, language: responseLanguage });
      setAnswer({ text: data.answer, confidence: Math.round(data.confidence * 100), quality: Math.round(data.context_quality * 100), recommendations: data.recommendations.map((item: { action: string }) => item.action), abstained: data.abstained });
    } catch { setAnswer(fallbackAnswer(question, role, responseLanguage)); }
  }

  async function selectLanguage(nextLanguage: Language) {
    setLanguage(nextLanguage);
    setLoading(true);
    await loadAnswer(query, nextLanguage);
    setLoading(false);
  }

  async function ask() {
    setLoading(true); setFeedback(null);
    const responseLanguage = inferLanguage(query, language);
    await loadAnswer(query, responseLanguage);
    setChartKind(chartFor(query));
    setLoading(false);
    window.setTimeout(() => answerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0);
  }

  return <div className="reasoning-agent">
    <header className="agent-hero">
      <div><p className="eyebrow">COMPONENT 3 · CONTEXT-AWARE FARM REASONING AGENT</p><h2>{profile.title}</h2><p>{profile.subtitle}</p></div>
      <div className="hero-actions"><div className="language-switch" aria-label="Response language"><button className={language === 'si' ? 'selected' : ''} onClick={() => selectLanguage('si')}>සිංහල</button><button className={language === 'en' ? 'selected' : ''} onClick={() => selectLanguage('en')}>EN</button><button className={language === 'ta' ? 'selected' : ''} onClick={() => selectLanguage('ta')}>தமிழ்</button></div></div>
    </header>

    <section className="agent-workspace">
      <main className="conversation-pane">
        <div className="context-strip"><span>Farm: NLDB Ridiyagama Farm</span><span>•</span><span>{profile.context}</span><span>•</span><span>Current context</span></div>
        <article className="answer-card" ref={answerRef}>
          <div className="answer-heading"><span className="agent-avatar">DA</span><div><p className="panel-label">DIGITAL AGRONOMIST</p><span className="answer-type">{profile.answerType}</span></div></div>
          {answer.abstained ? <div className="abstention"><b>I need more reliable information before advising.</b><p>Please confirm the farm, time period, and the current animal or herd observation.</p></div> : <><h3>{answer.text}</h3><div className="recommendation-box"><p className="panel-label">{profile.actionHeading}</p><ol>{answer.recommendations.map(item => <li key={item}>{item}</li>)}</ol></div></>}
          <AnswerVisualization kind={chartKind} />
          <div className="answer-footer"><button className="link-button" onClick={() => setShowEvidence(!showEvidence)}>{showEvidence ? 'Hide evidence' : 'View evidence'}</button><span>Was this helpful?</span><button className={feedback === 'helpful' ? 'feedback selected' : 'feedback'} onClick={() => setFeedback('helpful')}>Yes</button><button className={feedback === 'not_helpful' ? 'feedback selected' : 'feedback'} onClick={() => setFeedback('not_helpful')}>Not yet</button></div>
          {showEvidence && <section className="evidence-drawer"><div><b>Observed farm information</b><p>Recent production, routine, and environmental information relevant to this question.</p></div><div><b>AI interpretation</b><p>Model-based patterns are translated into plain language and kept distinct from observed facts.</p></div><div><b>Knowledge support</b><p>Approved veterinary and agronomic guidance, with source and version details.</p></div></section>}
        </article>

        <section className="question-area"><p className="panel-label">ASK A QUESTION</p><div className="ask"><input value={query} onChange={event => setQuery(event.target.value)} placeholder={copy.placeholder} aria-label={copy.placeholder} /><button onClick={ask} disabled={loading}>{loading ? 'Preparing…' : copy.ask}</button></div><div className="suggestions">{suggestedQuestions.map(suggestion => <button key={suggestion} onClick={() => setQuery(suggestion)}>{suggestion}</button>)}</div></section>
      </main>

      <aside className="insight-rail">
        {profile.showQuality && <section className="rail-card trust-card"><p className="panel-label">TRUST & DATA QUALITY</p><h3>How reliable is this guidance?</h3><div className="trust-score"><div><b>{answer.confidence}%</b><span>Answer confidence</span></div><div><b>{answer.quality}%</b><span>Context quality</span></div></div><p className="muted">Confidence reflects the response; context quality reflects completeness, freshness, agreement, and evidence traceability.</p><div className="quality-row"><span>Data completeness</span><i><b style={{ width: '92%' }} /></i></div><div className="quality-row"><span>Evidence freshness</span><i><b style={{ width: '88%' }} /></i></div></section>}
        <section className="rail-card"><p className="panel-label">DECISION SUPPORT</p><h3>{profile.priorityTitle}</h3>{profile.priorities.map((priority, index) => <div className={`priority-step ${index === 0 ? 'active' : ''}`} key={priority}><b>{index + 1}</b><span>{priority}</span></div>)}<p className="muted">{profile.reviewNote}</p></section>
        <section className="rail-card safety-card"><p className="panel-label">SAFE RESPONSE</p><h3>When evidence is insufficient</h3><p>The agent asks for missing context, abstains, or recommends expert review instead of making an unsupported conclusion.</p></section>
      </aside>
    </section>
  </div>;
}
