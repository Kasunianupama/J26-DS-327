/**
 * Simple view: "Download for Excel". The user ticks which parts go into the
 * workbook (one sheet each) and whether to add charts; the choice is remembered
 * in this browser only. The workbook itself is in English and by month.
 */

import { useEffect, useRef, useState } from 'react';
import { useRun } from '../source';
import { REPORT_PARTS, buildReport, type ReportPart } from './excelReport';
import { useT } from './i18n';

const KEY = 'pfoi.excel.parts';
const DEFAULT: ReportPart[] = ['summary', 'monthly', 'milk', 'reasons', 'herd', 'events'];

function loadChoice(): { parts: ReportPart[]; charts: boolean } {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const x = JSON.parse(raw) as { parts?: string[]; charts?: boolean };
      const parts = (x.parts ?? []).filter((p): p is ReportPart => REPORT_PARTS.some((r) => r.id === p));
      return { parts: parts.length ? parts : DEFAULT, charts: x.charts ?? true };
    }
  } catch { /* storage unavailable: use the default */ }
  return { parts: DEFAULT, charts: true };
}

export function ExportDialog({ months, onClose }: { months: number; onClose: () => void }) {
  const run = useRun();
  const t = useT();
  const [{ parts, charts }, setChoice] = useState(loadChoice);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    box.current?.querySelector<HTMLInputElement>('input')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = (next: { parts: ReportPart[]; charts: boolean }) => {
    setChoice(next);
    try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* not remembered */ }
  };
  const toggle = (id: ReportPart) => set({ charts, parts: parts.includes(id) ? parts.filter((p) => p !== id) : [...parts, id] });

  const download = () => {
    const ordered = REPORT_PARTS.map((p) => p.id).filter((id) => parts.includes(id));
    const blob = buildReport(run, months, ordered, charts);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `farm-outlook-${run.origin_date}${run.source === 'demo' ? '-practice-data' : ''}.xlsx`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    onClose();
  };

  return (
    <div className="pfie-mgr-modal" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pfie-mgr-dialog" role="dialog" aria-modal="true" aria-labelledby="pfie-export-h" ref={box}>
        <h3 id="pfie-export-h">{t('Download for Excel')}</h3>
        <p className="sub">{t('Tick what you want. Each one becomes a sheet with a table (and a chart). The file is in English, by month.')}</p>

        <div className="pfie-row tight">
          <button className="pfie-btn" onClick={() => set({ charts, parts: REPORT_PARTS.map((p) => p.id) })}>{t('Select all')}</button>
          <button className="pfie-btn" onClick={() => set({ charts, parts: [] })}>{t('Clear')}</button>
          <button className="pfie-btn" onClick={() => set({ charts, parts: DEFAULT })}>{t('The usual set')}</button>
        </div>

        <ul className="pfie-mgr-choices">
          {REPORT_PARTS.map((p) => (
            <li key={p.id}>
              <label>
                <input type="checkbox" checked={parts.includes(p.id)} onChange={() => toggle(p.id)} />
                <span>
                  <b>{t(p.label)}</b>{p.chart && charts && <span className="pfie-mgr-tag"></span>}
                  <small>{t(p.what)}</small>
                </span>
              </label>
            </li>
          ))}
        </ul>

        <label className="pfie-mgr-chartopt">
          <input type="checkbox" checked={charts} onChange={() => set({ parts, charts: !charts })} />{t('Add charts next to the tables')}
        </label>

        {run.source === 'demo' && <p className="pfie-mgr-note">{t('Practice data: every sheet says so.')}</p>}

        <div className="pfie-mgr-foot">
          <span className="pfie-mgr-note">{t('{a} of {b} chosen', { a: parts.length, b: REPORT_PARTS.length })}</span>
          <span className="spacer" />
          <button className="pfie-btn ghost" onClick={onClose}>{t('Cancel')}</button>
          <button className="pfie-btn primary" onClick={download} disabled={!parts.length}>{t('Download')} .xlsx</button>
        </div>
      </div>
    </div>
  );
}
