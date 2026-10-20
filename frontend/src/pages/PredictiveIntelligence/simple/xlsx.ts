/**
 * A small .xlsx writer for the simple view's Excel export: sheets with styled
 * cells, real Excel tables (filter buttons, banded rows) and native Excel charts
 * (line, column, stacked column, column + line). No dependency: the package is
 * written as plain Office Open XML into a stored (uncompressed) zip.
 */

/* ------------------------------------------------------------------ model */

/** Cell styles, defined in stylesXml below. */
export const S = {
  plain: 0, bold: 1, title: 2, int: 3, dec1: 4, pct: 5, note: 6, wrap: 7, label: 8, big: 9, subtitle: 10,
} as const;
export type StyleId = (typeof S)[keyof typeof S];

export type Value = string | number | null | undefined;
export type Cell = Value | { v: Value; s?: StyleId };

/** A block of rows that becomes an Excel table. `at` is the 0-based row of its header in the sheet. */
export interface TableSpec { name: string; at: number; col?: number; head: string[]; rows: Value[][]; styles?: (StyleId | undefined)[] }

export interface SeriesSpec { name: string; col: number; color: string; dash?: boolean; kind?: 'line' | 'bar' }
export interface ChartSpec {
  kind: 'line' | 'bar' | 'stacked' | 'combo';
  title: string;
  /** Table whose rows the chart reads; categories are its column `catCol`. */
  table: TableSpec;
  catCol: number;
  series: SeriesSpec[];
  yTitle?: string;
  /** Top-left cell (0-based) and size in cells. */
  at: { col: number; row: number; w?: number; h?: number };
}

export interface SheetSpec {
  name: string;
  widths?: number[];
  /** Free rows (titles, notes, key figures); tables are written over them at their `at` rows. */
  rows?: Cell[][];
  tables?: TableSpec[];
  charts?: ChartSpec[];
}

/* ------------------------------------------------------------------ helpers */

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const colName = (c: number) => { let s = ''; c += 1; while (c > 0) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); } return s; };
const ref = (r: number, c: number) => `${colName(c)}${r + 1}`;
const absRef = (sheet: string, r0: number, c: number, r1: number) => `'${sheet.replace(/'/g, "''")}'!$${colName(c)}$${r0 + 1}:$${colName(c)}$${r1 + 1}`;
const absCell = (sheet: string, r: number, c: number) => `'${sheet.replace(/'/g, "''")}'!$${colName(c)}$${r + 1}`;
const isNum = (v: Value): v is number => typeof v === 'number' && Number.isFinite(v);

/** Excel table names: letters, digits, underscore; unique in the workbook. */
export const tableName = (s: string) => s.replace(/[^A-Za-z0-9_]/g, '_').replace(/^([^A-Za-z_])/, '_$1');

/* ------------------------------------------------------------------ build */

export function buildXlsx(sheets: SheetSpec[]): Blob {
  return new Blob([buildXlsxBytes(sheets).buffer as ArrayBuffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}

/** The .xlsx file as bytes. */
export function buildXlsxBytes(sheets: SheetSpec[]): Uint8Array {
  const strings: string[] = [];
  const sIndex = new Map<string, number>();
  const str = (s: string) => { let i = sIndex.get(s); if (i === undefined) { i = strings.length; strings.push(s); sIndex.set(s, i); } return i; };

  const files: { name: string; data: string }[] = [];
  const overrides: string[] = [];
  let tableId = 0;
  let chartId = 0;
  let drawingId = 0;

  sheets.forEach((sheet, si) => {
    /* Lay out every cell: free rows first, then tables on top. */
    const grid = new Map<number, Map<number, { v: Value; s: number }>>();
    const put = (r: number, c: number, v: Value, s = 0) => {
      if (v === null || v === undefined || v === '') { if (s) { /* keep style only for headers */ } return; }
      if (!grid.has(r)) grid.set(r, new Map());
      grid.get(r)!.set(c, { v, s });
    };
    (sheet.rows ?? []).forEach((row, r) => row.forEach((cell, c) => {
      if (cell !== null && typeof cell === 'object') put(r, c, cell.v, cell.s ?? 0);
      else put(r, c, cell as Value, 0);
    }));
    (sheet.tables ?? []).forEach((t) => {
      const c0 = t.col ?? 0;
      t.head.forEach((h, j) => put(t.at, c0 + j, h, S.bold));
      t.rows.forEach((row, i) => row.forEach((v, j) => {
        const st = t.styles?.[j] ?? (isNum(v) ? (Number.isInteger(v) || Math.abs(v) >= 100 ? S.int : S.dec1) : S.wrap);
        put(t.at + 1 + i, c0 + j, v, st);
      }));
    });

    /* sheetData */
    const rowsXml = [...grid.keys()].sort((a, b) => a - b).map((r) => {
      const cells = [...grid.get(r)!.entries()].sort((a, b) => a[0] - b[0]).map(([c, { v, s }]) => {
        const at = ref(r, c);
        if (isNum(v)) return `<c r="${at}"${s ? ` s="${s}"` : ''}><v>${v}</v></c>`;
        return `<c r="${at}" t="s"${s ? ` s="${s}"` : ''}><v>${str(String(v))}</v></c>`;
      }).join('');
      return `<row r="${r + 1}">${cells}</row>`;
    }).join('');

    const cols = sheet.widths?.length
      ? `<cols>${sheet.widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('')}</cols>`
      : '';

    /* relationships of this sheet */
    const rels: string[] = [];
    let drawingXml = '';
    const charts = sheet.charts ?? [];
    if (charts.length) {
      drawingId += 1;
      const dRels: string[] = [];
      const anchors = charts.map((ch, k) => {
        chartId += 1;
        files.push({ name: `xl/charts/chart${chartId}.xml`, data: chartXml(sheet.name, ch) });
        overrides.push(`<Override PartName="/xl/charts/chart${chartId}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>`);
        dRels.push(`<Relationship Id="rId${k + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart${chartId}.xml"/>`);
        const { col, row, w = 9, h = 18 } = ch.at;
        return `<xdr:twoCellAnchor editAs="oneCell"><xdr:from><xdr:col>${col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>`
          + `<xdr:to><xdr:col>${col + w}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${row + h}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>`
          + `<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="${k + 2}" name="Chart ${k + 1}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>`
          + '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
          + `<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId${k + 1}"/>`
          + '</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>';
      }).join('');
      files.push({
        name: `xl/drawings/drawing${drawingId}.xml`,
        data: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">${anchors}</xdr:wsDr>`,
      });
      files.push({ name: `xl/drawings/_rels/drawing${drawingId}.xml.rels`, data: relsXml(dRels) });
      overrides.push(`<Override PartName="/xl/drawings/drawing${drawingId}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>`);
      rels.push(`<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing${drawingId}.xml"/>`);
      drawingXml = '<drawing r:id="rId1"/>';
    }

    const tableParts = (sheet.tables ?? []).filter((t) => t.rows.length).map((t) => {
      tableId += 1;
      const c0 = t.col ?? 0;
      const span = `${ref(t.at, c0)}:${ref(t.at + t.rows.length, c0 + t.head.length - 1)}`;
      const name = `${tableName(t.name)}_${tableId}`;
      files.push({
        name: `xl/tables/table${tableId}.xml`,
        data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          + `<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="${tableId}" name="${name}" displayName="${name}" ref="${span}" totalsRowShown="0">`
          + `<autoFilter ref="${span}"/><tableColumns count="${t.head.length}">${t.head.map((h, j) => `<tableColumn id="${j + 1}" name="${esc(h)}"/>`).join('')}</tableColumns>`
          + '<tableStyleInfo name="TableStyleMedium7" showFirstColumn="0" showLastColumn="0" showRowStripes="1" showColumnStripes="0"/></table>',
      });
      overrides.push(`<Override PartName="/xl/tables/table${tableId}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>`);
      const rid = `rId${rels.length + 1}`;
      rels.push(`<Relationship Id="${rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/table" Target="../tables/table${tableId}.xml"/>`);
      return `<tablePart r:id="${rid}"/>`;
    });

    files.push({
      name: `xl/worksheets/sheet${si + 1}.xml`,
      data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        + `<sheetViews><sheetView workbookViewId="0"${si === 0 ? ' tabSelected="1"' : ''} showGridLines="0"/></sheetViews>`
        + '<sheetFormatPr defaultRowHeight="15"/>'
        + cols
        + `<sheetData>${rowsXml}</sheetData>`
        + '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
        + '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        + drawingXml
        + (tableParts.length ? `<tableParts count="${tableParts.length}">${tableParts.join('')}</tableParts>` : '')
        + '</worksheet>',
    });
    if (rels.length) files.push({ name: `xl/worksheets/_rels/sheet${si + 1}.xml.rels`, data: relsXml(rels) });
    overrides.push(`<Override PartName="/xl/worksheets/sheet${si + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`);
  });

  const n = sheets.length;
  files.push({
    name: 'xl/workbook.xml',
    data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      + '<bookViews><workbookView activeTab="0"/></bookViews><sheets>'
      + sheets.map((s, i) => `<sheet name="${esc(s.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')
      + '</sheets></workbook>',
  });
  files.push({
    name: 'xl/_rels/workbook.xml.rels',
    data: relsXml([
      ...sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`),
      `<Relationship Id="rId${n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`,
      `<Relationship Id="rId${n + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>`,
    ]),
  });
  files.push({ name: 'xl/styles.xml', data: stylesXml() });
  files.push({
    name: 'xl/sharedStrings.xml',
    data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + `<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="${strings.length}" uniqueCount="${strings.length}">`
      + strings.map((s) => `<si><t xml:space="preserve">${esc(s)}</t></si>`).join('') + '</sst>',
  });
  files.push({
    name: '_rels/.rels',
    data: relsXml(['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>']),
  });
  files.unshift({
    name: '[Content_Types].xml',
    data: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
      + '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
      + overrides.join('') + '</Types>',
  });

  return zip(files);
}

const relsXml = (rels: string[]) => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
  + `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join('')}</Relationships>`;

function stylesXml() {
  const font = (o: { b?: boolean; i?: boolean; sz?: number; color?: string }) =>
    `<font>${o.b ? '<b/>' : ''}${o.i ? '<i/>' : ''}<sz val="${o.sz ?? 11}"/>${o.color ? `<color rgb="FF${o.color}"/>` : ''}<name val="Calibri"/><family val="2"/></font>`;
  const xf = (numFmt: number, fontId: number, fillId = 0, wrap = false) =>
    `<xf numFmtId="${numFmt}" fontId="${fontId}" fillId="${fillId}" borderId="0" xfId="0"${numFmt ? ' applyNumberFormat="1"' : ''}${fontId ? ' applyFont="1"' : ''}${fillId ? ' applyFill="1"' : ''}${wrap ? ' applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>' : '/>'}`;
  /* order must match S */
  const xfs = [
    xf(0, 0), // plain
    xf(0, 1), // bold
    xf(0, 2), // title
    xf(3, 0), // #,##0
    xf(164, 0), // 0.0
    xf(9, 0), // 0%
    xf(0, 3), // note (runs on to the right, no wrap)
    xf(0, 0, 0, true), // wrap
    xf(0, 1, 2), // label: bold on light fill
    xf(3, 4), // big number
    xf(0, 5), // subtitle
  ];
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0"/></numFmts>'
    + `<fonts count="6">${font({})}${font({ b: true })}${font({ b: true, sz: 18, color: '6C321A' })}${font({ i: true, sz: 10, color: '52665D' })}${font({ b: true, sz: 16, color: '17231F' })}${font({ b: true, sz: 13, color: '9A4F27' })}</fonts>`
    + '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF7E6DB"/><bgColor indexed="64"/></patternFill></fill></fills>'
    + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    + `<cellXfs count="${xfs.length}">${xfs.join('')}</cellXfs>`
    + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    + '</styleSheet>';
}

/* ------------------------------------------------------------------ charts */

const rich = (text: string, sz = 1200, b = true) =>
  `<c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="${sz}" b="${b ? 1 : 0}"/></a:pPr><a:r><a:rPr lang="en-GB" sz="${sz}" b="${b ? 1 : 0}"/><a:t>${esc(text)}</a:t></a:r></a:p></c:rich></c:tx>`;

function chartXml(sheet: string, ch: ChartSpec) {
  const t = ch.table;
  const c0 = t.col ?? 0;
  const r0 = t.at + 1;
  const r1 = t.at + t.rows.length;
  const cats = t.rows.map((r) => r[ch.catCol]);
  const catXml = `<c:cat><c:strRef><c:f>${absRef(sheet, r0, c0 + ch.catCol, r1)}</c:f><c:strCache><c:ptCount val="${cats.length}"/>`
    + cats.map((v, i) => `<c:pt idx="${i}"><c:v>${esc(String(v ?? ''))}</c:v></c:pt>`).join('') + '</c:strCache></c:strRef></c:cat>';

  const ser = (s: SeriesSpec, i: number, kind: 'line' | 'bar') => {
    const vals = t.rows.map((r) => r[s.col]);
    const fill = `<a:solidFill><a:srgbClr val="${s.color.replace('#', '').toUpperCase()}"/></a:solidFill>`;
    const spPr = kind === 'line'
      ? `<c:spPr><a:ln w="28575" cap="rnd">${fill}${s.dash ? '<a:prstDash val="dash"/>' : ''}<a:round/></a:ln></c:spPr><c:marker><c:symbol val="none"/></c:marker>`
      : `<c:spPr>${fill}</c:spPr><c:invertIfNegative val="0"/>`;
    return `<c:ser><c:idx val="${i}"/><c:order val="${i}"/>`
      + `<c:tx><c:strRef><c:f>${absCell(sheet, t.at, c0 + s.col)}</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>${esc(s.name)}</c:v></c:pt></c:strCache></c:strRef></c:tx>`
      + spPr + catXml
      + `<c:val><c:numRef><c:f>${absRef(sheet, r0, c0 + s.col, r1)}</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="${vals.length}"/>`
      + vals.map((v, k) => (isNum(v) ? `<c:pt idx="${k}"><c:v>${v}</c:v></c:pt>` : '')).join('')
      + '</c:numCache></c:numRef></c:val>'
      + (kind === 'line' ? '<c:smooth val="0"/>' : '')
      + '</c:ser>';
  };

  const axes = '<c:axId val="500100"/><c:axId val="500200"/>';
  const bars = (list: SeriesSpec[], stacked: boolean) => `<c:barChart><c:barDir val="col"/><c:grouping val="${stacked ? 'stacked' : 'clustered'}"/><c:varyColors val="0"/>`
    + list.map((s) => ser(s, ch.series.indexOf(s), 'bar')).join('')
    + `<c:gapWidth val="60"/>${stacked ? '<c:overlap val="100"/>' : ''}${axes}</c:barChart>`;
  const lines = (list: SeriesSpec[]) => '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>'
    + list.map((s) => ser(s, ch.series.indexOf(s), 'line')).join('')
    + `<c:marker val="1"/>${axes}</c:lineChart>`;

  let plots = '';
  if (ch.kind === 'line') plots = lines(ch.series);
  else if (ch.kind === 'bar') plots = bars(ch.series, false);
  else if (ch.kind === 'stacked') plots = bars(ch.series, true);
  else plots = bars(ch.series.filter((s) => s.kind !== 'line'), false) + lines(ch.series.filter((s) => s.kind === 'line'));

  const txPr = '<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900"/></a:pPr><a:endParaRPr lang="en-GB"/></a:p></c:txPr>';
  const grid = '<c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="E2E9E5"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>';
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    + '<c:roundedCorners val="0"/><c:chart>'
    + `<c:title>${rich(ch.title)}<c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>`
    + `<c:plotArea><c:layout/>${plots}`
    + '<c:catAx><c:axId val="500100"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/>'
    + '<c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="low"/>'
    + `${txPr}<c:crossAx val="500200"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>`
    + `<c:valAx><c:axId val="500200"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/>${grid}`
    + (ch.yTitle ? `<c:title>${rich(ch.yTitle, 900, false)}<c:overlay val="0"/></c:title>` : '')
    + `<c:numFmt formatCode="#,##0" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>${txPr}`
    + '<c:crossAx val="500100"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>'
    + '</c:plotArea><c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend><c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/>'
    + '</c:chart></c:chartSpace>';
}

/* ------------------------------------------------------------------ zip (stored) */

const CRC = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

function zip(files: { name: string; data: string }[]): Uint8Array {
  const enc = new TextEncoder();
  const parts: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  files.forEach((f) => {
    const name = enc.encode(f.name);
    const data = enc.encode(f.data);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
    local.setUint16(8, 0, true); local.setUint16(10, 0, true); local.setUint16(12, 0x21, true);
    local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true); local.setUint16(28, 0, true);
    parts.push(new Uint8Array(local.buffer), name, data);
    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true); cd.setUint16(4, 20, true); cd.setUint16(6, 20, true); cd.setUint16(8, 0x0800, true);
    cd.setUint16(10, 0, true); cd.setUint16(12, 0, true); cd.setUint16(14, 0x21, true);
    cd.setUint32(16, crc, true); cd.setUint32(20, data.length, true); cd.setUint32(24, data.length, true);
    cd.setUint16(28, name.length, true); cd.setUint32(42, offset, true);
    central.push(new Uint8Array(cd.buffer), name);
    offset += 30 + name.length + data.length;
  });
  const cdSize = central.reduce((s, b) => s + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((s, b) => s + b.length, 0));
  let p = 0;
  all.forEach((b) => { out.set(b, p); p += b.length; });
  return out;
}
