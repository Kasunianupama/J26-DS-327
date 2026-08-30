import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Point = Record<string, string | number>;

export function ContextChart({ chart, label, language }: { chart: { type: string; title: string; data?: Point[] }; label?: string; language?: 'en' | 'si' | 'ta' }) {
  if (!chart.data?.length) return null;
  const isBar = chart.type === 'bar';
  const xKey = isBar ? 'animal_id' : 'date';
  const yKey = isBar ? 'risk_score' : 'milk_litres';
  const metric = isBar ? (language === 'si' ? 'අවධානම් ලකුණු' : language === 'ta' ? 'கவன மதிப்பெண்' : 'Attention score') : (language === 'si' ? 'කිරි නිෂ්පාදනය' : language === 'ta' ? 'பால் உற்பத்தி' : 'Milk production');
  return <section className="context-chart"><p>{label ?? 'CHART'}</p><h3>{chart.title}</h3><ResponsiveContainer width="100%" height={250}>{isBar ? <BarChart data={chart.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} /><YAxis domain={[0, 100]} unit="%" /><Tooltip /><Bar dataKey={yKey} name={metric} fill="#2d7f69" radius={[5, 5, 0, 0]} /></BarChart> : <LineChart data={chart.data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey={xKey} tickFormatter={(value) => String(value).slice(5)} /><YAxis unit=" L" /><Tooltip /><Line type="monotone" dataKey={yKey} name={metric} stroke="#286fab" strokeWidth={3} dot={false} activeDot={{ r: 5 }} /></LineChart>}</ResponsiveContainer></section>;
}
