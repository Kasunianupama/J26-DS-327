/** Shared C3 browser conversation types; no credentials or account identifiers. */
export type ScenarioContext = { animal_ref?: string | null; thi_mean?: number | null; milkings_per_day?: number | null; mode?: 'thi' | 'milkings' | 'combined' | null };
export type Context = {
  topic?: string | null; reference_date?: string | null; target_period?: string | null;
  grain?: string; series?: string; awaiting?: string | null; scenario?: ScenarioContext | null;
};
export type Reply = {
  status: string; answer: string; language?: 'en' | 'si' | 'ta'; interpretation_mode?: string; title?: string; context: Context; provider: string;
  demo: boolean; cloud_processing: boolean; warnings?: string[];
  answer_generation?: 'grounded_milk_v1'; generation_status?: string; generation_model?: string;
  action?: 'c2_scenario'; evidence?: Record<string, unknown> | null;
};
export type Turn = { id: string; question: string; response?: Reply; error?: string };
export type Conversation = {
  id: string; updatedAt: string; language?: 'en' | 'si' | 'ta'; turns: Turn[]; context: Context;
  reference: string; target: string; grain: string; datesOpen: boolean;
};
export type HistoryStore = { version: 1; activeId: string; conversations: Conversation[] };
