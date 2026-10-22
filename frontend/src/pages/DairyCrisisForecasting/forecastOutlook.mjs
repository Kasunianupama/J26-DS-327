// Only selects existing real forecast rows. No warning scores or inferred bounds.
const DAY = 86400000;
export function futureOutlook(rows, startDate, horizon, now = new Date()) {
  const today = now.toISOString().slice(0, 10);
  const start = Date.parse(startDate);
  const empty = (reason, dates = []) => ({ available: false, reason, dates, rows: [],
    origin: rows[0]?.origin_date ?? null, intervalAvailable: false });
  if (![1, 7].includes(horizon) || !/^\d{4}-\d{2}-\d{2}$/.test(startDate) || !Number.isFinite(start) || startDate <= today)
    return empty('Choose a future target date. Historical assessments are separate.');
  const dates = Array.from({ length: horizon }, (_, i) => new Date(start + i * DAY).toISOString().slice(0, 10));
  if (!rows.length) return empty('No current C1 forecast run is available.', dates);
  const origin = rows[0].origin_date, core = rows[0].core_version;
  if (!origin || origin > today || !core || rows.some(r => r.origin_date !== origin || r.core_version !== core ||
      r.model_version !== 'pfoi-1.2.0-dev')) return empty('Forecast origin or provenance is not eligible.', dates);
  const selected = dates.map(date => rows.filter(r => r.target_period === date));
  if (selected.some(found => found.length !== 1))
    return empty('The available C1 run does not uniquely cover every selected future day.', dates);
  const forecasts = selected.map(found => found[0]);
  if (forecasts.some(r => r.quality_flag !== 'ok' || !Number.isFinite(r.forecast) || r.forecast < 0 ||
      !Number.isInteger(r.horizon) || r.horizon !== (Date.parse(r.target_period) - Date.parse(origin)) / DAY + 1))
    return empty('Selected forecast quality, values or horizons are not eligible.', dates);
  if (forecasts.some(r => !r.created_at || !/(?:Z|[+-]\d{2}:\d{2})$/.test(r.created_at) || !Number.isFinite(Date.parse(r.created_at))))
    return empty('Publication timing is not supplied by the current C1 API. A timely future outlook cannot be verified.', dates);
  if (forecasts.some(r => Date.parse(r.created_at) > now.getTime() || new Date(r.created_at).toISOString().slice(0, 10) > origin))
    return empty('This run was published after its stated origin or after the current cutoff; it is not a timely-origin forecast.', dates);
  if (forecasts.some(r => !((r.lower == null && r.upper == null) ||
      (Number.isFinite(r.lower) && Number.isFinite(r.upper) && 0 <= r.lower && r.lower <= r.forecast && r.forecast <= r.upper))))
    return empty('The supplied uncertainty range is inconsistent.', dates);
  return { available: true, reason: 'Published milk-production forecast context; no warning category is assigned.',
    dates, rows: forecasts, origin, intervalAvailable: forecasts.every(r => r.lower != null && r.upper != null) };
}
