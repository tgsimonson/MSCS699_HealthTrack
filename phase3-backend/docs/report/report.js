const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Header, AlignmentType, PageNumber, PageBreak, Table, TableRow,
  TableCell, WidthType, BorderStyle } = require("docx");

const FONT = "Times New Roman", SZ = 24, DBL = { line: 480, before: 0, after: 0 };
const runs = (t, o = {}) => t.split(/(\*[^*]+\*)/g).filter((x) => x).map((x) =>
  x.startsWith("*") && x.endsWith("*") ? new TextRun({ text: x.slice(1, -1), italics: true, font: FONT, size: SZ, ...o })
    : new TextRun({ text: x, font: FONT, size: SZ, ...o }));
const body = (t) => new Paragraph({ children: runs(t), spacing: DBL, indent: { firstLine: 720 } });
const center = (t, o = {}) => new Paragraph({ children: runs(t, o), alignment: AlignmentType.CENTER, spacing: DBL });
const left = (t, o = {}) => new Paragraph({ children: runs(t, o), spacing: DBL, keepNext: true });
const blank = () => new Paragraph({ children: [new TextRun({ text: "", font: FONT, size: SZ })], spacing: DBL });

const T = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, line = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const W = [5160, 1000, 1600, 1600];
const cell = (t, i, { bold = false, top = none, bottom = none } = {}) => new TableCell({
  width: { size: W[i], type: WidthType.DXA }, borders: { top, bottom, left: none, right: none },
  margins: { top: 30, bottom: 30, left: 80, right: 80 },
  children: [new Paragraph({ alignment: i ? AlignmentType.CENTER : AlignmentType.LEFT, spacing: { line: 240 },
    children: [new TextRun({ text: String(t), bold, font: FONT, size: 20 })] })] });
const rows = T.table;
const table = new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: W, rows: [
  new TableRow({ tableHeader: true, children: ["Operation", "n", "p50 (ms)", "p95 (ms)"].map((h, i) =>
    cell(h, i, { bold: true, top: line, bottom: line })) }),
  ...rows.map((r, k) => new TableRow({ cantSplit: true, children: [r[0], r[1], r[2].toFixed(1), r[3].toFixed(1)].map((v, i) =>
    cell(v, i, { bottom: k === rows.length - 1 ? line : none })) })) ] });

const kids = [blank(), blank(), blank(), center(T.title, { bold: true }), blank(), center("Todd Simonson"),
  center("MSCS 699 Computer Science Capstone"), center("Michael Solomon"), center("November 8, 2026"),
  new Paragraph({ children: [new PageBreak()] }), center(T.title, { bold: true })];
for (const s of T.sections) {
  if (s.heading) kids.push(center(s.heading, { bold: true }));
  for (const p of s.paras) {
    if (p === "[TABLE1]") {
      kids.push(left("Table 1", { bold: true }), left("*Endpoint Latency Measured In-Process on the Development Machine*"), table,
        new Paragraph({ spacing: DBL, children: runs("*Note.* Times include authentication, authorization, validation, and the audit write; p50 is the median.") }));
    } else kids.push(body(p));
  }
}
kids.push(new Paragraph({ children: [new PageBreak()] }), center("References", { bold: true }));
for (const r of T.references) kids.push(new Paragraph({ children: runs(r), spacing: DBL, indent: { left: 720, hanging: 720 } }));

const doc = new Document({ styles: { default: { document: { run: { font: FONT, size: SZ } } } }, sections: [{
  properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
  headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
    children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: SZ })] })] }) },
  children: kids }] });
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(process.argv[3], b); console.log("ok"); });
