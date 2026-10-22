/** C3 milk comparison and local Excel download use the same saved evidence snapshot. */
import {useState} from 'react';
import {api} from '../../services/api';
import {t,LOCALES,type Language} from './i18n';
import {milkReport,lineSegments,type MilkDay} from './milkReport';

const number=(value:number|null)=>value===null?null:new Intl.NumberFormat('en-GB',{maximumFractionDigits:2}).format(value);
const series=[{key:'delpro_litres' as const,label:'Recorded milk (DelPro)',color:'#a45a31'},
  {key:'shipments_litres' as const,label:'Milk shipments',color:'#3e8578'}];

export function MilkReportView({evidence,language}:{evidence:Record<string,unknown>;language:Language}){
  const report=milkReport(evidence),[downloading,setDownloading]=useState(false),[error,setError]=useState('');
  if(!report)return null;
  const dateLabel=(value:string)=>new Intl.DateTimeFormat(LOCALES[language],{day:'numeric',month:'short',timeZone:'UTC'}).format(new Date(value));
  const status=(day:MilkDay)=>!day.record_present?'Day not recorded':day.data_gap===true?'Data gap flagged':day.data_gap===null?'Gap status unknown':'Recorded';
  const values=report.days.flatMap(day=>[day.delpro_litres,day.shipments_litres]).filter((item):item is number=>item!==null);
  const low=Math.min(0,...values),high=Math.max(1,...values),span=high-low||1;
  const x=(index:number)=>58+index*(620/13),y=(value:number)=>205-(value-low)/span*165;
  async function download(){
    if(downloading||!report)return;
    setDownloading(true);setError('');
    try{
      const {data,headers}=await api.post<Blob>('/agent/reports/milk.xlsx',{report,language},{responseType:'blob',timeout:20000});
      if(!String(headers['content-type']).includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')||!data.size||data.size>4*1024*1024)throw new Error('Invalid download');
      const url=URL.createObjectURL(data),link=document.createElement('a');
      link.href=url;link.download=`farm-x-milk-${report.observed_date}.xlsx`;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch{setError(t(language,'The Excel download failed. Your saved answer is unchanged. Try again.'));}
    finally{setDownloading(false);}
  }
  return <section className="c3-milk-report" aria-label={t(language,'Milk summary chart and report')}>
    <div className="c3-milk-heading"><div><span className="c3-eyebrow">{t(language,'YOUR RECORDED MILK')}</span><h4>{t(language,'Daily milk and weekly comparison')}</h4>
      <p>{dateLabel(report.days[0].date)} – {dateLabel(report.observed_date)} · {t(language,'Historical records')}</p></div>
      <button type="button" onClick={()=>void download()} disabled={downloading}>↓ {t(language,downloading?'Preparing Excel…':'Download Excel')}</button></div>
    <div className="c3-milk-cards">{(['delpro','shipments'] as const).map(key=>{
      const item=report.sources[key];return <div className="c3-milk-card" key={key}><strong>{t(language,key==='delpro'?'Recorded milk (DelPro)':'Milk shipments')}</strong>
        <span className="c3-milk-total">{number(item.current_litres)??t(language,'Not recorded')}<small>{item.current_litres!==null?' L':''}</small></span>
        <p>{item.current_observed_days}{t(language,' of 7 days')} · {t(language,'Latest period')}</p>
        <div>{t(language,'Previous period')}: {number(item.previous_litres)??t(language,'Not recorded')}{item.previous_litres!==null?' L':''} ({item.previous_observed_days}/7)</div>
        <span className="c3-milk-change">{item.change_pct===null?t(language,'Comparison unavailable'):`${item.change_pct>0?'+':''}${number(item.change_pct)}% ${t(language,'weekly change')}`}</span>
      </div>;
    })}</div>
    <p className="c3-milk-note">{t(language,'Milk recorded and milk shipped are separate measurements. They are not added together.')}</p>
    {values.length?<div className="c3-milk-plot"><svg viewBox="0 0 720 250" role="img" aria-label={t(language,'Daily milk chart in litres. Missing measurements are gaps.')}>
      <text x="10" y="19" className="c3-milk-axis">L</text>
      {[0,1,2,3].map(tick=>{const value=low+span*tick/3;return <g key={tick}><line x1="58" x2="678" y1={y(value)} y2={y(value)} className="c3-milk-grid"/><text x="49" y={y(value)+4} textAnchor="end" className="c3-milk-axis">{number(value)}</text></g>;})}
      <line x1={x(6.5)} x2={x(6.5)} y1="27" y2="211" className="c3-milk-divider"/>
      {[0,3,6,10,13].map(index=><text key={index} x={x(index)} y="232" textAnchor="middle" className="c3-milk-axis">{dateLabel(report.days[index].date)}</text>)}
      {series.map(({key,label,color})=><g key={key}>{lineSegments(report.days,key,x,y).map((path,index)=><path key={index} d={path} fill="none" stroke={color} strokeWidth="2.5"/>)}
        {report.days.map((day,index)=>day[key]!==null?<circle key={day.date} cx={x(index)} cy={y(day[key]!)} r="4" fill={color} stroke="white" strokeWidth="1.5" tabIndex={0} aria-label={`${day.date}, ${t(language,label)}, ${number(day[key])} L. ${t(language,status(day))}`}><title>{`${day.date}: ${number(day[key])} L · ${t(language,label)} · ${t(language,status(day))}`}</title></circle>:null)}</g>)}
    </svg></div>:<p>{t(language,'No daily milk measurements were supplied for this period.')}</p>}
    <div className="c3-milk-legend">{series.map(item=><span key={item.key}><i style={{background:item.color}}/>{t(language,item.label)}</span>)}</div>
    <p className="c3-milk-note">{t(language,'Missing measurements appear as gaps, not zero. The dashed divider separates the previous and latest seven days. Flagged or incomplete periods cannot support a reliable weekly change.')}</p>
    <details className="c3-milk-table"><summary>{t(language,'View daily figures')}</summary><div><table><caption>{t(language,'Daily figures used in this answer and download')}</caption><thead><tr><th>{t(language,'Date')}</th><th>{t(language,'Recorded milk (DelPro)')} (L)</th><th>{t(language,'Milk shipments')} (L)</th><th>{t(language,'Record status')}</th></tr></thead><tbody>{report.days.map(day=><tr key={day.date}><th scope="row">{day.date}</th><td>{number(day.delpro_litres)??t(language,'Not recorded')}</td><td>{number(day.shipments_litres)??t(language,'Not recorded')}</td><td>{t(language,status(day))}</td></tr>)}</tbody></table></div></details>
    {error&&<p className="c3-error" role="alert">{error}</p>}
  </section>;
}
