/** Versioned local-only chat storage; failed or unrecognised saves stay visible. */
import type { Context, Conversation, HistoryStore, Reply, Turn } from './chatTypes';

export const HISTORY_KEY = 'farmx.c3.chat-history.v1';
type StorageAccess = Pick<Storage, 'getItem' | 'setItem'>;
type LoadResult = { store: HistoryStore; notice: string; blocked: boolean };
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const nullableText = (value: unknown) => value === null || text(value);
const contextKeys = new Set(['topic', 'reference_date', 'target_period', 'grain', 'series', 'awaiting']);

function validScenario(value: unknown): boolean {
  if (value === null) return true;
  return record(value) && Object.entries(value).every(([key,item]) => {
    if (!['animal_ref','thi_mean','milkings_per_day','mode'].includes(key)) return false;
    if (item === null) return true;
    if (key === 'animal_ref') return text(item) && /^A[A-Za-z0-9_-]{1,159}$/.test(item) && item !== 'A_PLACEHOLDER';
    if (key === 'mode') return ['thi','milkings','combined'].includes(String(item));
    return typeof item === 'number' && Number.isFinite(item) && (key !== 'milkings_per_day' || item > 0);
  });
}
function validContext(value: unknown): value is Context {
  return record(value) && Object.entries(value).every(([key,item]) => key === 'scenario'
    ? validScenario(item) : contextKeys.has(key) && nullableText(item));
}
function validReply(value: unknown): value is Reply {
  return record(value) && (value.language === undefined || ['en','si','ta'].includes(String(value.language))) && text(value.status) && text(value.answer) && validContext(value.context)
    && (value.action === undefined || value.action === 'c2_scenario')
    && ['local_template', 'local_qwen'].includes(String(value.provider)) && value.demo === false && value.cloud_processing === false
    && (value.provider !== 'local_qwen' || (value.status === 'success' && value.answer_generation === 'grounded_milk_v1' && value.generation_status === 'success'))
    && (value.title === undefined || text(value.title))
    && (value.warnings === undefined || (Array.isArray(value.warnings) && value.warnings.every(text)))
    && (value.evidence === undefined || value.evidence === null || record(value.evidence));
}
function validTurn(value: unknown): value is Turn {
  return record(value) && text(value.id) && text(value.question)
    && (value.error === undefined || text(value.error))
    && (value.response === undefined || validReply(value.response));
}
function validConversation(value: unknown): value is Conversation {
  return record(value) && (value.language === undefined || ['en','si','ta'].includes(String(value.language))) && text(value.id) && text(value.updatedAt) && Number.isFinite(Date.parse(value.updatedAt))
    && Array.isArray(value.turns) && value.turns.every(validTurn) && validContext(value.context)
    && text(value.reference) && text(value.target) && ['daily', 'weekly', 'monthly'].includes(String(value.grain))
    && typeof value.datesOpen === 'boolean';
}

export function newConversation(id: string = crypto.randomUUID()): Conversation {
  return { id, updatedAt: new Date().toISOString(), turns: [], context: {}, reference: '', target: '', grain: 'daily', datesOpen: false };
}
export function emptyHistory(id: string = crypto.randomUUID()): HistoryStore {
  const conversation = newConversation(id);
  return { version: 1, activeId: conversation.id, conversations: [conversation] };
}
export function decodeHistory(raw: string): HistoryStore {
  const value: unknown = JSON.parse(raw);
  if (!record(value) || value.version !== 1 || !text(value.activeId)
      || !Array.isArray(value.conversations) || !value.conversations.length
      || !value.conversations.every(validConversation)) throw new Error('Invalid saved history');
  const conversations = value.conversations as Conversation[];
  if (new Set(conversations.map(item => item.id)).size !== conversations.length
      || !conversations.some(item => item.id === value.activeId)) throw new Error('Invalid conversation selection');
  return { version: 1, activeId: value.activeId, conversations: conversations.map(item => ({
    ...item, turns: item.turns.map(turn => turn.response || turn.error ? turn : {
      ...turn, error: 'This request was interrupted before an answer was saved. Please send the question again.',
    }),
  })) };
}
export function readHistory(storage: StorageAccess, fallback = emptyHistory(), key = HISTORY_KEY): LoadResult {
  try {
    const raw = storage.getItem(key);
    return { store: raw === null ? fallback : decodeHistory(raw), notice: '', blocked: false };
  } catch {
    return { store: fallback, blocked: true, notice: 'Saved chats could not be opened. You can continue in memory. Use Clear saved chats to reset local history.' };
  }
}
export function saveHistory(storage: StorageAccess, store: HistoryStore, key = HISTORY_KEY): string {
  try {
    storage.setItem(key, JSON.stringify(store));
    return '';
  } catch {
    return 'Chat history could not be saved in this browser. Keep this page open to retain the current conversation, or free browser storage and retry.';
  }
}
export function conversationTitle(conversation: Conversation): string {
  return conversation.turns[0]?.question.trim() || 'New conversation';
}
