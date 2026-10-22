/** C3 local profiles: independent role histories, offline backup and restore. */
import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { useUser } from '../../context/UserContext';
import type { Role } from '../../types/api';
import type { HistoryStore } from './chatTypes';
import LocalAssistant from './LocalAssistant';
import { t, message, type Language } from './i18n';
import { PROFILE_KEY, ROLE_LABELS, decodeProfiles, defaultProfiles, historyKey, makeBackup, decodeBackup, restoreBackup } from './profileBackups';

export default function ProfileAssistant() {
  const { role, setRole } = useUser();
  const [language,setLanguage]=useState<Language>('en');
  const [initial] = useState(() => {
    try { const raw = localStorage.getItem(PROFILE_KEY); return { profiles: raw === null ? defaultProfiles() : decodeProfiles(raw), blocked: false }; }
    catch { return { profiles: defaultProfiles(), blocked: true }; }
  });
  const [profiles, setProfiles] = useState(initial.profiles);
  const [blocked, setBlocked] = useState(initial.blocked);
  const [notice, setNotice] = useState(initial.blocked ? 'Local profiles could not be opened. Existing profile records will not be overwritten automatically.' : '');
  const [revision, setRevision] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const upload = useRef<HTMLInputElement>(null);
  const profile = profiles.profiles.find(item => item.id === profiles.activeId)!;
  const scope = historyKey(profile.id, role);
  useEffect(() => {
    function changed(event: StorageEvent) {
      if (event.key === PROFILE_KEY || event.key === null) {
        setBlocked(true); setNotice('Profiles changed in another tab. Reload this page before modifying profiles or restoring backups.');
      }
    }
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);
  function persist(next: typeof profiles) {
    try { localStorage.setItem(PROFILE_KEY, JSON.stringify(next)); setProfiles(next); setNotice(''); }
    catch { setNotice('Profile changes could not be saved. Check browser storage; your existing profiles remain selected.'); }
  }
  function addProfile() {
    const used = new Set(profiles.profiles.map(item => item.label));
    let number = 1; while (used.has(`Profile ${number}`)) number++;
    const added = { id: crypto.randomUUID(), label: `Profile ${number}` };
    persist({ ...profiles, activeId: added.id, profiles: [...profiles.profiles, added] });
  }
  function backup(history: HistoryStore, wholeProfile: boolean) {
    try {
      const data = makeBackup(localStorage, profile, role, history, wholeProfile);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url; link.download = `farmx-c3-${profile.id}-${wholeProfile ? 'all-roles' : role}-${data.createdAt.slice(0, 10)}.json`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('Backup download requested. Keep this file on a trusted device; it contains saved conversations and evidence.');
    } catch { setNotice('Backup could not be created. Check local browser storage; no incomplete profile backup was downloaded.'); }
  }
  async function restore(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file) return;
    setRestoring(true);
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('Select a backup smaller than 10 MB.');
      let data;
      try { data = decodeBackup(await file.text()); }
      catch { throw new Error('This is not a valid C3 profile backup. No saved chats were changed.'); }
      const roles = Object.keys(data.roles) as Role[];
      const existing = profiles.profiles.find(item => item.id === data.profile.id);
      const label = existing?.label ?? data.profile.label;
      if (!window.confirm(message(language,'Restore {profile} for {roles}? Existing conversations with matching IDs will be kept unchanged. Other profiles and roles will not be changed.',{profile:label,roles:roles.map(item=>t(language,ROLE_LABELS[item])).join(', ')}))) return;
      const result = restoreBackup(localStorage, data, profiles);
      setProfiles(result.profiles); setRevision(value => value + 1);
      setRole(roles.includes(role) ? role : roles[0]);
      setNotice(message(language,'Restored {added} conversations. Kept {skipped} existing conversations with matching IDs. Other profile and role histories were preserved.',{added:result.added,skipped:result.skipped}));
    } catch (error) { setNotice(error instanceof Error ? error.message : 'Restore failed. Keep your original backup.'); }
    finally { setRestoring(false); }
  }
  return <div className="c3-profile-workspace">
    <section className="c3-profile-controls" aria-label="Local chat profile">
      <label>{t(language,'Chat profile')}<select value={profile.id} disabled={blocked || restoring} onChange={event => persist({ ...profiles, activeId: event.target.value })}>
        {profiles.profiles.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
      <button onClick={addProfile} disabled={blocked || restoring}>＋ {t(language,'Add profile')}</button>
      <span className="c3-profile-role">{t(language,ROLE_LABELS[role])}</span>
      <span>{t(language,'Local profiles organise chats. They do not provide sign-in or access control.')}</span>
    </section>
    {notice && <p className="c3-profile-notice" role="status">{t(language,notice)}</p>}
    <input ref={upload} type="file" accept="application/json,.json" hidden onChange={event => void restore(event)} aria-label="Restore C3 profile backup" />
    <LocalAssistant key={`${scope}:${revision}`} storageKey={scope} scopeLabel={`${profile.label} · ${t(language,ROLE_LABELS[role])}`}
      onBackup={backup} onRestore={() => upload.current?.click()} backupDisabled={blocked || restoring} onLanguageChange={setLanguage} />
  </div>;
}
