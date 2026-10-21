const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const page = readFileSync(
  path.join(__dirname, '../src/pages/InterventionSimulator/index.tsx'),
  'utf8',
);

test('What-If scenario selector contains only THI and milking frequency', () => {
  const selector = page.match(/<label>Input category<select[\s\S]*?<\/select>/);
  assert.ok(selector, 'scenario category selector is present');
  const options = [...selector[0].matchAll(/<option value="([^"]+)">/g)].map((match) => match[1]);
  assert.deepEqual(options, ['heat', 'management']);
  assert.match(page, /Available scenarios: hypothetical THI exposure changes and milking frequency changes\./);
});
