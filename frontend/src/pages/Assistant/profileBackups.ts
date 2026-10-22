/** Local profile/role namespaces and validated backups; no cloud or identity service. */
import type { Role } from '../../types/api';
import type { HistoryStore } from './chatTypes';
import { decodeHistory } from './chatHistory';

export const PROFILE_KEY = 'farmx.c3.profiles.v1';
export const ROLES: Role[] = ['farm_worker', 'veterinarian', 'farm_manager', 'board_management'];
export const ROLE_LABELS: Record<Role, string> = { farm_worker: 'Farm worker', veterinarian: 'Veterinarian', farm_manager: 'Farm manager', board_management: 'Board management' };
export type ChatProfile = { id: string; label: string };
export type Profiles = { version: 1; activeId: string; profiles: ChatProfile[] };
export type ProfileBackup = { format: 'farmx-c3-profile-backup'; version: 1; createdAt: string; profile: ChatProfile; roles: Partial<Record<Role, HistoryStore>> };
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
function validProfile(value: unknown): value is ChatProfile {
  return record(value) && typeof value.id === 'string' && /^[a-zA-Z0-9_-]{1,80}$/.test(value.id)
    && typeof value.label === 'string' && value.label.trim().length > 0 && value.label.length <= 40;
}
export function defaultProfiles(): Profiles {
  return { version: 1, activeId: 'default', profiles: [{ id: 'default', label: 'Profile 1' }] };
}
export function decodeProfiles(raw: string): Profiles {
  const value: unknown = JSON.parse(raw);
  if (!record(value) || value.version !== 1 || !Array.isArray(value.profiles) || !value.profiles.length
      || !value.profiles.every(validProfile) || typeof value.activeId !== 'string'
      || !value.profiles.some(p => p.id === value.activeId)
      || new Set(value.profiles.map(p => p.id)).size !== value.profiles.length) throw new Error('Invalid profiles');
  return { version: 1, activeId: value.activeId, profiles: value.profiles.map(p => ({ id: p.id, label: p.label })) };
}
export function historyKey(profileId: string, role: Role): string {
  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(profileId) || !ROLES.includes(role)) throw new Error('Invalid history scope');
  return `farmx.c3.scoped-history.v1.${profileId}.${role}`;
}
export function mergeHistory(current: HistoryStore, incoming: HistoryStore): { store: HistoryStore; added: number; skipped: number } {
  const known = new Set(current.conversations.map(item => item.id));
  const populated = incoming.conversations.filter(item => item.turns.length);
  const added = populated.filter(item => !known.has(item.id));
  const currentHasChats = current.conversations.some(item => item.turns.length);
  const conversations = [...current.conversations, ...added];
  const activeId = currentHasChats || !added.length ? current.activeId
    : added.some(item => item.id === incoming.activeId) ? incoming.activeId : added[0].id;
  return { store: { version: 1, activeId, conversations }, added: added.length, skipped: populated.length - added.length };
}
export function makeBackup(storage: Store, profile: ChatProfile, role: Role, current: HistoryStore, wholeProfile: boolean): ProfileBackup {
  const roles: Partial<Record<Role, HistoryStore>> = { [role]: decodeHistory(JSON.stringify(current)) };
  if (wholeProfile) for (const candidate of ROLES) {
    if (candidate === role) continue;
    const raw = storage.getItem(historyKey(profile.id, candidate));
    if (raw !== null) roles[candidate] = decodeHistory(raw);
  }
  return { format: 'farmx-c3-profile-backup', version: 1, createdAt: new Date().toISOString(), profile: { ...profile }, roles };
}
export function decodeBackup(raw: string): ProfileBackup {
  const value: unknown = JSON.parse(raw);
  if (!record(value) || value.format !== 'farmx-c3-profile-backup' || value.version !== 1
      || !validProfile(value.profile) || typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt))
      || !record(value.roles) || !Object.keys(value.roles).length
      || Object.keys(value.roles).some(role => !ROLES.includes(role as Role))) throw new Error('Invalid backup');
  const roles: Partial<Record<Role, HistoryStore>> = {};
  for (const [role, history] of Object.entries(value.roles)) roles[role as Role] = decodeHistory(JSON.stringify(history));
  return { format: 'farmx-c3-profile-backup', version: 1, createdAt: value.createdAt, profile: { id: value.profile.id, label: value.profile.label }, roles };
}
export function restoreBackup(storage: Store, backup: ProfileBackup, profiles: Profiles) {
  // Revalidate even programmatic callers. Stage changes before touching storage.
  backup = decodeBackup(JSON.stringify(backup));
  profiles = decodeProfiles(JSON.stringify(profiles));
  const nextProfiles: Profiles = { ...profiles, activeId: backup.profile.id,
    profiles: profiles.profiles.some(p => p.id === backup.profile.id) ? profiles.profiles : [...profiles.profiles, backup.profile] };
  const writes: [string, string][] = [];
  let added = 0, skipped = 0;
  for (const [role, incoming] of Object.entries(backup.roles)) {
    const key = historyKey(backup.profile.id, role as Role);
    const raw = storage.getItem(key);
    if (raw === null) {
      writes.push([key, JSON.stringify(incoming)]);
      added += incoming.conversations.filter(item => item.turns.length).length;
    } else {
      const merged = mergeHistory(decodeHistory(raw), incoming);
      writes.push([key, JSON.stringify(merged.store)]); added += merged.added; skipped += merged.skipped;
    }
  }
  writes.push([PROFILE_KEY, JSON.stringify(nextProfiles)]);
  const previous = writes.map(([key]) => [key, storage.getItem(key)] as const);
  try {
    for (const [key, value] of writes) storage.setItem(key, value);
  } catch {
    let rolledBack = true;
    for (const [key, value] of previous.slice().reverse()) {
      try { if (value === null) storage.removeItem(key); else storage.setItem(key, value); }
      catch { rolledBack = false; }
    }
    throw new Error(rolledBack ? 'Restore could not be saved. Previous saved histories were retained.'
      : 'Restore could not finish and storage rollback was incomplete. Keep your backup and check browser storage before continuing.');
  }
  return { profiles: nextProfiles, added, skipped };
}
