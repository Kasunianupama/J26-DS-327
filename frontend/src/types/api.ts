export type Role = 'farm_worker' | 'veterinarian' | 'farm_manager' | 'nldb_management';
export interface AgentResponse { answer:string; confidence:number; context_quality:number; intent:string; evidence: unknown[]; recommendations:{action:string;priority:string}[]; visualizations: unknown[]; abstained:boolean }
