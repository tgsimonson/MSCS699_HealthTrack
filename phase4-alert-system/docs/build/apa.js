// builds an apa 7 student paper (.docx) from a json spec: title page, body with level 1 and 2 headings,
// tables and figures, references. usage: node apa.js spec.json out.docx
const fs = require("fs");
const path = require("path");
const { Document, Packer, Paragraph, TextRun, Header, AlignmentType, PageNumber, PageBreak, Table, TableRow,
  TableCell, WidthType, BorderStyle, ImageRun } = require("docx");

const FONT = "Times New Roman", SZ = 24, DBL = { line: 480, before: 0, after: 0 };
const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const base = path.dirname(path.resolve(process.argv[2]));

// *italic* and **bold** inline markup
const runs = (t, o = {}) => t.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).filter((x) => x).map((x) => {
  if (x.startsWith("**")) return new TextRun({ text: x.slice(2, -2), bold: true, font: FONT, size: SZ, ...o });
  if (x.startsWith("*")) return new TextRun({ text: x.slice(1, -1), italics: true, font: FONT, size: SZ, ...o });
  return new TextRun({ text: x, font: FONT, size: SZ, ...o });
});
const body = (t) => new Paragraph({ children: runs(t), spacing: DBL, indent: { firstLine: 720 } });
const center = (t, o = {}) => new Paragraph({ children: runs(t, o), alignment: AlignmentType.CENTER, spacing: DBL });
const left = (t, o = {}, keep = true) => new Paragraph({ children: runs(t, o), spacing: DBL, keepNext: keep });
// table and figure labels: single spaced with a little air, so tables stay with their titles on short papers
const label = (t, o = {}, before = 120) => new Paragraph({ children: runs(t, o), keepNext: true,
  spacing: { line: 240, before, after: 60 } });
const blank = () => new Paragraph({ children: [new TextRun({ text: "", font: FONT, size: SZ })], spacing: DBL });

const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const rule = { style: BorderStyle.SINGLE, size: 4, color: "000000" };

function table(t) {
  const widths = t.columns.map((c) => c.width);
  const total = widths.reduce((a, b) => a + b, 0);
  const size = t.font_size || 18;
  const cell = (text, i, { bold = false, top = none, bottom = none } = {}) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, borders: { top, bottom, left: none, right: none },
    margins: { top: 20, bottom: 20, left: 60, right: 60 },
    children: [new Paragraph({ spacing: { line: 240 }, alignment: (t.columns[i].align === "center")
      ? AlignmentType.CENTER : AlignmentType.LEFT, children: runs(String(text), { size, bold }) })] });
  const rows = [new TableRow({ tableHeader: true, children: t.columns.map((c, i) =>
    cell(c.label, i, { bold: true, top: rule, bottom: rule })) })];
  t.rows.forEach((r, k) => rows.push(new TableRow({ cantSplit: true, children: r.map((v, i) =>
    cell(v, i, { bottom: k === t.rows.length - 1 ? rule : none })) })));
  const out = [label(`Table ${t.number}`, { bold: true }), label(`*${t.title}*`, {}, 0),
    new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, rows })];
  if (t.note) out.push(new Paragraph({ spacing: { line: 240, before: 60, after: 240 }, children: runs(`*Note.* ${t.note}`, { size: 20 }) }));
  else out.push(blank());
  return out;
}

function figure(f) {
  const img = fs.readFileSync(path.resolve(base, f.image));
  const w = Math.round(f.width_in * 96), h = Math.round(w * f.aspect);
  const out = [label(`Figure ${f.number}`, { bold: true }), label(`*${f.title}*`, {}, 0),
    new Paragraph({ keepNext: !!f.note, spacing: { before: 0, after: 0 }, children: [new ImageRun({ type: "png", data: img,
      transformation: { width: w, height: h } })] })];
  if (f.note) out.push(new Paragraph({ spacing: { line: 240, before: 60, after: 240 }, children: runs(`*Note.* ${f.note}`, { size: 20 }) }));
  return out;
}

const kids = [blank(), blank(), blank(), center(spec.title, { bold: true }), blank(), center(spec.author),
  center(spec.course), center(spec.instructor), center(spec.date),
  new Paragraph({ children: [new PageBreak()] }), center(spec.title, { bold: true })];
for (const s of spec.sections) {
  if (s.heading) kids.push(s.level === 2 ? left(s.heading, { bold: true }) : center(s.heading, { bold: true }));
  for (const p of s.paras) {
    if (typeof p === "string") kids.push(body(p));
    else if (p.table) kids.push(...table(p.table));
    else if (p.figure) kids.push(...figure(p.figure));
  }
}
if (spec.references && spec.references.length) {
  // page-break-before on the heading itself: a separate break paragraph leaves a blank page when the body ends
  // exactly at the bottom of a page
  kids.push(new Paragraph({ children: runs("References", { bold: true }), alignment: AlignmentType.CENTER,
    spacing: DBL, pageBreakBefore: true }));
  for (const r of spec.references) kids.push(new Paragraph({ children: runs(r), spacing: DBL, indent: { left: 720, hanging: 720 } }));
}

const doc = new Document({ styles: { default: { document: { run: { font: FONT, size: SZ } } } }, sections: [{
  properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
  headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
    children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: SZ })] })] }) },
  children: kids }] });
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(process.argv[3], b); console.log("wrote", process.argv[3]); });
