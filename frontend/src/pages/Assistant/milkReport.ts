/** Read the saved C3 milk snapshot; preserve nulls and build unconnected chart segments. */
export type MilkDay = { date: string; delpro_litres: number|null; shipments_litres: number|null; record_present: boolean; data_gap: boolean|null };
export type MilkSource = { current_litres: number|null; previous_litres: number|null; current_observed_days: number; previous_observed_days: number; comparison_supported: boolean; change_pct: number|null };
export type MilkReport = { kind:'milk_summary'; version:1; source:'published_core_aggregates'; core_version:string; observed_date:string; days:MilkDay[]; sources:{delpro:MilkSource;shipments:MilkSource}; warnings:string[] };
const object=(value:unknown):value is Record<string,unknown>=>typeof value==='object'&&value!==null&&!Array.isArray(value);
const numeric=(value:unknown)=>value===null || typeof value==='number'&&Number.isFinite(value);
const dayString=(value:unknown):value is string=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;

export function milkReport(evidence:Record<string,unknown>):MilkReport|null{
  const item=evidence.milk_report;
  if(!object(item)||item.kind!=='milk_summary'||item.version!==1||item.source!=='published_core_aggregates'||!dayString(item.observed_date)
    ||typeof item.core_version!=='string'||!item.core_version||item.core_version.length>160||!Array.isArray(item.days)||item.days.length!==14
    ||!object(item.sources)||Object.keys(item.sources).sort().join(',')!=='delpro,shipments'
    ||!Array.isArray(item.warnings)||item.warnings.length>30||!item.warnings.every(note=>typeof note==='string'&&note.length<=1000))return null;
  const end=Date.parse(item.observed_date);
  if(!item.days.every((day,index)=>object(day)&&dayString(day.date)&&Date.parse(day.date)===end-(13-index)*86400000
    &&numeric(day.delpro_litres)&&(day.delpro_litres===null||(day.delpro_litres as number)>0)&&numeric(day.shipments_litres)&&typeof day.record_present==='boolean'&&(day.data_gap===null||typeof day.data_gap==='boolean')
    &&(day.record_present || day.delpro_litres===null&&day.shipments_litres===null&&day.data_gap===null)))return null;
  for(const key of ['delpro','shipments']){
    const source=item.sources[key];
    if(!object(source)||!numeric(source.current_litres)||!numeric(source.previous_litres)||!numeric(source.change_pct)
      ||!['current_observed_days','previous_observed_days'].every(field=>typeof source[field]==='number'&&Number.isInteger(source[field])&&(source[field] as number)>=0&&(source[field] as number)<=7)
      ||typeof source.comparison_supported!=='boolean'||(!source.comparison_supported&&source.change_pct!==null))return null;
    const days=item.days as MilkDay[],field=key==='delpro'?'delpro_litres':'shipments_litres',summary=source as MilkSource;
    const total=(subset:MilkDay[])=>{const values=subset.map(day=>day[field]).filter((value):value is number=>value!==null);return {count:values.length,value:values.length?values.reduce((sum,value)=>sum+value,0):null};};
    const same=(left:number|null,right:number|null)=>left===null&&right===null||left!==null&&right!==null&&Number.isFinite(left)&&Number.isFinite(right)&&Math.abs(left-right)<=Math.max(1e-6,Math.abs(right)*1e-9);
    const previous=total(days.slice(0,7)),current=total(days.slice(7));
    if(previous.count!==summary.previous_observed_days||current.count!==summary.current_observed_days||!same(previous.value,summary.previous_litres)||!same(current.value,summary.current_litres))return null;
    if(summary.comparison_supported && (previous.count!==7||current.count!==7||previous.value===null||previous.value<=0||current.value===null
      ||!days.every(day=>day.record_present&&day.data_gap===false)||!same(summary.change_pct,(current.value-previous.value)/previous.value*100)))return null;
  }
  return item as MilkReport;
}

export function lineSegments(days:MilkDay[],field:'delpro_litres'|'shipments_litres',x:(index:number)=>number,y:(value:number)=>number):string[]{
  const result:string[]=[];let path='';
  days.forEach((day,index)=>{
    const value=day[field];
    if(value===null){if(path)result.push(path);path='';return;}
    path+=`${path?' L':'M'}${x(index).toFixed(2)},${y(value).toFixed(2)}`;
  });
  if(path)result.push(path);return result;
}
