import { useEffect, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import './ChartFullscreen.css';

type Point = Record<string, string | number>;
type Language = 'en' | 'si' | 'ta';

export function ContextChart({ chart, label, language }: { chart: { type: string; title: string; data?: Point[] }; label?: string; language?: Language }) {
  const containerRef = useRef<HTMLElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === containerRef.current);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);
  if (!chart.data?.length) return null;
  const toggleFullscreen = async () => { if (document.fullscreenElement) await document.exitFullscreen(); else await containerRef.current?.requestFullscreen?.(); };
  const isBar = chart.type === 'bar'; const xKey = isBar ? 'animal_id' : 'date'; const yKey = isBar ? 'risk_score' : 'milk_litres';
  const metric = isBar ? (language === 'si' ? 'අවධානම් ලකුණු' : language === 'ta' ? 'கவன மதிப்பெண்' : 'Attention score') : (language === 'si' ? 'කිරි නිෂ්පාදනය' : language === 'ta' ? 'பால் உற்பத்தி' : 'Milk production');
  const expandLabel = language === 'si' ? 'ප්‍රස්තාරය සම්පූර්ණ තිරයෙන් බලන්න' : language === 'ta' ? 'வரைபடத்தை முழுத்திரையில் காண்க' : 'View chart fullscreen'; const exitLabel = language === 'si' ? 'සම්පූර්ණ තිරයෙන් ඉවත් වන්න' : language === 'ta' ? 'முழுத்திரையிலிருந்து வெளியேறு' : 'Exit fullscreen';
  return <section className={`context-chart${isFullscreen ? ' is-fullscreen' : ''}`} ref={containerRef}><div className="chart-heading"><div><p>{label ?? 'CHART'}</p><h3>{chart.title}</h3></div><button className="chart-fullscreen" type="button" onClick={() => void toggleFullscreen()} aria-label={isFullscreen ? exitLabel : expandLabel} title={isFullscreen ? exitLabel : expandLabel}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6" /></svg></button></div><ResponsiveContainer width="100%" height={isFullscreen ? 620 : 250}>{isBar ? <BarChart data={chart.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis domain={[0, 100]} unit="%" /><Tooltip /><Bar dataKey={yKey} name={metric} fill="#2d7f69" radius={[5, 5, 0, 0]} /></BarChart> : <LineChart data={chart.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} tickFormatter={(value) => String(value).slice(5)} /><YAxis unit=" L" /><Tooltip /><Line type="monotone" dataKey={yKey} name={metric} stroke="#286fab" strokeWidth={3} dot={false} activeDot={{ r: 5 }} /></LineChart>}</ResponsiveContainer></section>;
}
