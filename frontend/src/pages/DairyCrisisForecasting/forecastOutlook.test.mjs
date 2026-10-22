// Fictional forecast rows only; no network, database or clock dependencies.
import test from 'node:test';
import assert from 'node:assert/strict';
import { futureOutlook } from './forecastOutlook.mjs';
const now = new Date('2026-01-10T12:00:00Z');
function rows() {
  return Array.from({ length: 7 }, (_, i) => ({ origin_date: '2026-01-10', target_period: `2026-01-${11+i}`,
    horizon: i + 2, forecast: 100, lower: 80, upper: 120, model_version: 'pfoi-1.2.0-dev',
    core_version: 'fictional-core', quality_flag: 'ok', created_at: '2026-01-10T08:00:00Z' }));
}
test('tomorrow and complete next seven days retain original forecasts and daily intervals', () => {
  const input = rows(), before = JSON.stringify(input);
  assert.equal(futureOutlook(input, '2026-01-11', 1, now).rows.length, 1);
  const result = futureOutlook(input, '2026-01-11', 7, now);
  assert.equal(result.available, true); assert.equal(result.intervalAvailable, true);
  assert.equal(result.rows[0].forecast, 100); assert.equal(JSON.stringify(input), before);
});
test('past dates, gaps, duplicate target rows and stale coverage stay unavailable', () => {
  assert.equal(futureOutlook(rows(), '2026-01-10', 1, now).available, false);
  assert.equal(futureOutlook(rows().slice(1), '2026-01-11', 7, now).available, false);
  assert.equal(futureOutlook([...rows(), rows()[0]], '2026-01-11', 1, now).available, false);
  assert.equal(futureOutlook(rows(), '2026-02-01', 1, now).available, false);
});
test('missing publication timestamp never becomes inferred midnight', () => {
  const input = rows(); delete input[0].created_at;
  const result = futureOutlook(input, '2026-01-11', 1, now);
  assert.equal(result.available, false); assert.deepEqual(result.rows, []);
  assert.match(result.reason, /Publication timing/);
});
test('post-origin reconstruction is never a timely historical forecast', () => {
  const input = rows(); input[0].created_at = '2026-01-11T00:00:00Z';
  assert.match(futureOutlook(input, '2026-01-11', 1, now).reason, /published after/);
});
test('quality, origin, provenance, horizon and malformed ranges fail safely', () => {
  for (const change of [{ quality_flag: 'low_recording' }, { model_version: 'demo' },
    { origin_date: '2026-01-12' }, { core_version: null }, { horizon: 1 }, { lower: 110 },
    { forecast: NaN }, { upper: null }]) {
    const input = rows(); Object.assign(input[0], change);
    assert.equal(futureOutlook(input, '2026-01-11', 1, now).available, false);
  }
});
test('missing paired interval stays absent without fabrication', () => {
  const input = rows(); input[0].lower = null; input[0].upper = null;
  const result = futureOutlook(input, '2026-01-11', 1, now);
  assert.equal(result.available, true); assert.equal(result.intervalAvailable, false);
});
