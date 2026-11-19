// ViraLift genome map, mounted through st.components.v2 by ui/genome_map.py,
// which builds `data`. One component, five views:
//   matrix     record x gene status grid under the reference bar (Results)
//   tracks     reference over one record, genes joined by ribbons (Results)
//   reference  labelled reference bar (Setup preview)
//   picker     reference bar whose genes toggle the FASTA selection (Export)
//   evidence   reference genes lifted onto a record, an annotated span under them (Review names)
// Streamlit calls this function again on every rerun with the same parent, so
// everything that should survive a rerun (zoom, alignment mode) lives on the
// root element. Events go back to Python with setTriggerValue:
//   select {record, gene} (matrix) or gene name (tracks), focus (gene), pick (gene).

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const nf = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const pct = (v, d = 0) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const r1 = (v) => Math.round(v * 10) / 10;
const fits = (name, w) => w >= String(name).length * 6.4 + 12;

function niceStep(span, px, every = 90) {
  const target = span / Math.max(1, px / every);
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(target, 1))));
  for (const m of [1, 2, 5, 10]) if (m * p >= target) return m * p;
  return 10 * p;
}
const fmtBp = (v, step) => (step >= 1000 ? v / 1000 + " kb" : nf(v));

function arrowPath(xa, xb, y, h, strand) {
  const w = Math.max(xb - xa, 1.5), tip = Math.min(7, w * 0.4);
  xb = xa + w;
  if (strand === "-") return `M${r1(xa + tip)},${y}L${r1(xb)},${y}L${r1(xb)},${y + h}L${r1(xa + tip)},${y + h}L${r1(xa)},${y + h / 2}Z`;
  return `M${r1(xa)},${y}L${r1(xb - tip)},${y}L${r1(xb)},${y + h / 2}L${r1(xb - tip)},${y + h}L${r1(xa)},${y + h}Z`;
}

// Lanes: for CDS the first three lanes are reading frames +1/+2/+3, so
// overlapping ORFs separate the way they do in the genome; anything that still
// collides goes to an extra lane below. Mature peptides share one lane.
function packLanes(items, base) {
  const occ = [];
  const free = (l, s, e) => !(occ[l] || []).some(([a, b]) => s <= b && e >= a);
  items.sort((a, b) => a.s - b.s || (a.ord || 0) - (b.ord || 0)).forEach((it) => {
    let l = it.pref;
    if (!free(l, it.s, it.e)) { l = base; while (!free(l, it.s, it.e)) l++; }
    (occ[l] = occ[l] || []).push([it.s, it.e]);
    it.lane = l;
  });
  return items;
}
const frameOf = (start, isCDS) => (isCDS ? (((start - 1) % 3) + 3) % 3 : 0);
const laneCount = (items, base) => Math.max(base, ...items.map((i) => i.lane + 1));

function svgSize(svg, W, H) {
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);
}

// ── entry ─────────────────────────────────────────────────────────────
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let root = parentElement.querySelector(".gm");
  if (!root) {
    root = document.createElement("div");
    root.className = "gm";
    root.innerHTML =
      '<div class="gm-bar" hidden></div>' +
      '<div class="gm-scroll"><svg class="gm-svg" xmlns="http://www.w3.org/2000/svg" role="img"></svg></div>' +
      // The matrix scrolls on its own; its header (reference bar, links, gene names) sticks on top.
      '<div class="gm-matrix" hidden>' +
      '<svg class="gm-mhead" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Reference genes"></svg>' +
      '<svg class="gm-mrows" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Gene status per record"></svg>' +
      "</div>" +
      '<div class="gm-foot" hidden></div>' +
      '<div class="gm-tip" hidden></div>';
    parentElement.appendChild(root);
    root.gm = { views: {}, align: null, hover: null, drag: null, width: 0 };
    wire(root);
    root.gm.ro = new ResizeObserver(() => {
      const w = Math.floor(root.clientWidth);
      if (w && w !== root.gm.width) { root.gm.width = w; draw(root); }
    });
    root.gm.ro.observe(root);
  }
  root.gm.data = data || {};
  root.gm.emit = setTriggerValue;
  draw(root);
  return () => root.gm.ro && root.gm.ro.disconnect();
}

function draw(root) {
  const d = root.gm.data;
  root.dataset.view = d.view || "";
  const svg = root.querySelector(".gm-svg");
  const bar = root.querySelector(".gm-bar");
  const foot = root.querySelector(".gm-foot");
  const matrix = root.querySelector(".gm-matrix");
  bar.hidden = true;
  foot.hidden = true;
  matrix.hidden = d.view !== "matrix";
  root.querySelector(".gm-scroll").hidden = d.view === "matrix";
  if (!d.view) { svg.innerHTML = ""; return; }
  if (d.view === "matrix") { drawMatrix(root, matrix, d); return; }
  const W = Math.max(d.view === "evidence" ? 360 : 560, Math.floor(root.clientWidth) || 800);
  if (d.view === "tracks") drawTracks(root, svg, bar, W, d);
  else if (d.view === "reference") drawReference(svg, W, d, null);
  else if (d.view === "picker") drawPicker(svg, foot, W, d);
  else if (d.view === "evidence") drawEvidence(svg, W, d);
  svg.setAttribute("aria-label", { tracks: "Reference and record gene map", reference: "Reference gene map", picker: "Pick genes to export", evidence: "Where the name sits on the record" }[d.view] || "Genome map");
}

const statusOf = (d, i) => (d.statuses && d.statuses[i]) || ["", "", "warn"];

// ── matrix ────────────────────────────────────────────────────────────
// Two SVGs in one scroll box: the header (ruler, reference bar, links, gene
// names) is position: sticky, the rows scroll under it. Width comes from the
// box's client width so a classic scrollbar never forces a sideways scroll.
function drawMatrix(root, box, d) {
  const head = box.querySelector(".gm-mhead"), body = box.querySelector(".gm-mrows");
  const W = Math.max(560, Math.floor(box.clientWidth) || 800);
  const ref = d.ref, refLen = ref.length;
  const L = 118, R = 54, x0 = L, x1 = W - R;
  const sx = (v) => x0 + ((v - 1) / Math.max(1, refLen - 1)) * (x1 - x0);
  const isCDS = ref.ftype === "CDS", base = isCDS ? 3 : 1;
  const genes = ref.genes.map((g) => ({ name: g[0], start: g[1], end: g[2], label: g[4] }));
  const items = packLanes(genes.map((g) => ({ s: g.start, e: g.end, pref: frameOf(g.start, isCDS), g })), base);
  const nL = laneCount(items, base);
  const laneH = 7, laneGap = 2, refTop = 34;
  const refBottom = refTop + nL * (laneH + laneGap) - laneGap;
  const cols = [...d.columns, "__extra"];
  const colIndex = Object.fromEntries(d.columns.map((c, i) => [c, i]));
  const labelOf = Object.fromEntries(genes.map((g) => [g.name, g.label]));
  const colW = (x1 - x0) / cols.length;
  const cx = (i) => x0 + i * colW + colW / 2;
  const headY = refBottom + 46, headH = headY + 8, rowsTop = 2, rowH = 24;
  const rows = d.rows || [];
  const H = rowsTop + Math.max(rows.length, 1) * rowH + 8;
  const step = niceStep(refLen, x1 - x0, 110);
  let s = "";
  for (let t = step; t < refLen; t += step) s += `<line class="tick" x1="${r1(sx(t))}" x2="${r1(sx(t))}" y1="${refTop - 10}" y2="${refTop - 6}"/><text class="tick-label" x="${r1(sx(t))}" y="${refTop - 14}" text-anchor="middle">${fmtBp(t, step)}</text>`;
  s += `<line class="backbone" x1="${r1(sx(1))}" x2="${r1(sx(refLen))}" y1="${refTop - 6}" y2="${refTop - 6}"/>`;
  s += `<text class="track-label" x="8" y="${refTop + 4}">Reference</text><text class="track-sub" x="8" y="${refTop + 17}">${esc(ref.id)}</text>`;
  const fi = d.focus != null && d.focus in colIndex ? colIndex[d.focus] : -1;
  // The focus band runs through both SVGs; each clips the rounded end it does not own.
  const band = (y, h) => (fi >= 0 ? `<rect class="col-band" x="${r1(x0 + fi * colW + 1)}" y="${y}" width="${r1(colW - 2)}" height="${h}" rx="6"/>` : "");
  s += band(headY - 15, headH - headY + 30);
  const ym = (refBottom + headY - 14) / 2;
  items.forEach((it) => {
    const g = it.g, i = colIndex[g.name];
    if (i === undefined) return;
    const y = refTop + it.lane * (laneH + laneGap), mx = r1((sx(g.start) + sx(g.end)) / 2), c = r1(cx(i));
    s += `<path class="fan${d.focus === g.name ? " is-focus" : ""}" d="M${mx},${y + laneH}C${mx},${ym} ${c},${ym} ${c},${headY - 14}"/>`;
  });
  items.forEach((it) => {
    const g = it.g, y = refTop + it.lane * (laneH + laneGap);
    s += `<rect class="ov-gene${d.focus === g.name ? " is-focus" : ""}" x="${r1(sx(g.start))}" y="${y}" width="${r1(Math.max(1.5, sx(g.end) - sx(g.start)))}" height="${laneH}" rx="1.5" data-focus="${esc(g.name)}" data-tip="ref|${esc(g.name)}"/>`;
  });
  cols.forEach((c, i) => {
    const extra = c === "__extra";
    const text = extra ? "extra" : labelOf[c] || c;
    s += `<text class="col-label${d.focus === c ? " is-focus" : ""}${extra ? " is-extra" : ""}" x="${r1(cx(i))}" y="${headY}" text-anchor="middle"${extra ? "" : ` data-focus="${esc(c)}" tabindex="0" role="button" aria-label="${esc(text)} in every record"`}>${esc(text)}</text>`;
  });
  svgSize(head, W, headH);
  head.innerHTML = s;

  s = band(-12, H + 6);
  rows.forEach((row, ri) => {
    const [id, healthKey, cells, extras, passed, total] = row;
    const y = rowsTop + ri * rowH, sel = id === d.selected;
    const [hLabel, hTone] = (d.health && d.health[healthKey]) || [healthKey, "neutral"];
    s += `<g class="ov-row${sel ? " is-selected" : ""}" data-rec="${esc(id)}">`;
    s += `<rect class="row-band" x="2" y="${y}" width="${W - 4}" height="${rowH}" rx="6"/>`;
    s += `<circle class="dot tone-${esc(hTone)}" cx="11" cy="${y + rowH / 2}" r="3.5"><title>${esc(hLabel)}</title></circle>`;
    s += `<text class="row-label" x="21" y="${y + rowH / 2 + 4}" tabindex="0" role="button" aria-label="Open ${esc(id)}">${esc(id)}</text>`;
    cells.forEach((cell, i) => {
      const x = x0 + i * colW + 3, w = Math.max(4, colW - 6);
      if (!cell) { s += `<rect class="cell c-none" x="${r1(x)}" y="${y + 4}" width="${r1(w)}" height="${rowH - 8}" rx="3"/>`; return; }
      const [key, , tone] = statusOf(d, cell[0]);
      const cls = key === d.absent ? "absent" : tone;
      s += `<rect class="cell c-${esc(cls)}" x="${r1(x)}" y="${y + 4}" width="${r1(w)}" height="${rowH - 8}" rx="3" data-gene="${esc(d.columns[i])}" data-tip="cell|${ri}|${i}"/>`;
      if (cell[5]) s += `<path class="short-flag" d="M${r1(x + w - 7)},${y + 4}h7v7z"/>`;
    });
    if (extras.length) s += `<text class="extra-count" x="${r1(cx(cols.length - 1))}" y="${y + rowH / 2 + 4}" text-anchor="middle" data-tip="extra|${ri}">+${extras.length}</text>`;
    s += `<text class="row-stat" x="${W - 10}" y="${y + rowH / 2 + 4}" text-anchor="end">${passed}/${total}</text>`;
    s += "</g>";
  });
  if (!rows.length) s += `<text class="empty" x="${W / 2}" y="${rowsTop + 18}" text-anchor="middle">No records match this filter.</text>`;
  svgSize(body, W, H);
  body.innerHTML = s;

  // A new set of rows (filter, search, new run) starts at the top. A selection
  // made outside the matrix (Previous / Next, Worth a look) scrolls its row
  // into view; a click inside the matrix is already in view and moves nothing.
  const gm = root.gm, signature = `${rows.length}|${rows.length ? rows[0][0] : ""}`;
  if (gm.matrixRows !== signature) { box.scrollTop = 0; gm.matrixRows = signature; gm.matrixSelected = undefined; }
  if (d.selected !== gm.matrixSelected) {
    gm.matrixSelected = d.selected;
    const ri = rows.findIndex((row) => row[0] === d.selected);
    if (ri >= 0) {
      const top = headH + rowsTop + ri * rowH, view = box.clientHeight;
      if (top < box.scrollTop + headH || top + rowH > box.scrollTop + view) {
        box.scrollTop = Math.max(0, top - headH - (view - headH - rowH) / 2);
      }
    }
  }
}

// ── tracks ────────────────────────────────────────────────────────────
function trackGeometry(root, W, d) {
  const rec = d.record, ref = d.ref;
  const align = root.gm.align || d.align || "ref";
  const off = align === "ref" ? rec.offset : 0;
  const len = rec.length, flip = !!rec.flipped;
  const disp = (v) => (flip ? len - v + 1 : v); // record position -> display position
  const span = (a, b) => (flip ? [disp(b), disp(a)] : [a, b]); // record interval -> display interval
  const lo = Math.min(1, 1 + off), hi = Math.max(ref.length, len + off), pad = (hi - lo) * 0.01;
  return { align, off, len, flip, disp, span, full: [lo - pad, hi + pad], key: `${rec.id}|${align}` };
}

function drawTracks(root, svg, bar, W, d) {
  const ref = d.ref, rec = d.record;
  const G = trackGeometry(root, W, d);
  const views = root.gm.views;
  if (!views[G.key]) views[G.key] = G.full.slice();
  const [d0, d1] = views[G.key];
  const L = 92, R = 14, x0 = L, x1 = W - R, k = (x1 - x0) / (d1 - d0);
  const sx = (v) => x0 + (v - d0) * k;
  root.gm.geom = { x0, x1, full: G.full, key: G.key };

  bar.hidden = false;
  bar.innerHTML =
    `<div class="seg" role="group" aria-label="Coordinates">` +
    `<button type="button" data-align="ref" class="${G.align === "ref" ? "is-active" : ""}">Aligned to reference</button>` +
    `<button type="button" data-align="own" class="${G.align === "own" ? "is-active" : ""}">Own coordinates</button></div>` +
    `<div class="zoom"><button type="button" data-zoom="out" aria-label="Zoom out">−</button><button type="button" data-zoom="in" aria-label="Zoom in">+</button><button type="button" data-zoom="fit">Fit</button></div>` +
    (G.flip ? `<span class="note">Reverse-complement record, drawn mirrored</span>` : "");

  const isCDS = ref.ftype === "CDS", base = isCDS ? 3 : 1;
  const feats = rec.features.map((f, i) => ({
    i, name: f[0], label: f[1], si: f[2], method: f[3], rs: f[4], re: f[5], qs: f[6], qe: f[7],
    strand: f[8], cov: f[9], ident: f[10], raws: f[11], rawe: f[12], rescue: f[13], short: f[14],
  }));
  const byName = {};
  feats.forEach((f) => { if (f.rs != null && !(f.name in byName)) byName[f.name] = f; });
  const refItems = packLanes(ref.genes.map((g) => ({ s: g[1], e: g[2], pref: frameOf(g[1], isCDS), g })), base);
  const nRef = laneCount(refItems, base);
  const located = feats.filter((f) => f.qs != null);
  const qItems = packLanes(located.map((f) => {
    const [a, b] = G.span(f.qs, f.qe);
    return { s: a, e: b, pref: frameOf(a, isCDS), f, ord: f.rs == null ? 1 : 0 };
  }), base);
  const nQ = laneCount(qItems, base);
  const raws = located.filter((f) => f.raws != null);
  const laneH = 18, gap = 5, refAxisY = 26, refLane0 = 36;
  const refBottom = refLane0 + nRef * (laneH + gap) - gap;
  const ribTop = refBottom + 5, ribBot = ribTop + 78;
  const qLane0 = ribBot + 5, qBottom = qLane0 + nQ * (laneH + gap) - gap;
  const rawY = qBottom + 12, rawH = 8;
  const qAxisY = (raws.length ? rawY + rawH : qBottom) + 12;
  const H = qAxisY + 26;
  const sel = d.selected, off = G.off;
  const toneOf = (f) => statusOf(d, f.si)[2];
  const keyOf = (f) => statusOf(d, f.si)[0];
  let s = `<defs><clipPath id="gm-clip"><rect x="${x0}" y="0" width="${x1 - x0}" height="${H}"/></clipPath>` +
    `<pattern id="gm-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" class="hatch-bg"/><line x1="0" y1="0" x2="0" y2="5" class="hatch-line"/></pattern></defs>`;

  s += `<text class="track-label" x="6" y="${refLane0 + 11}">Reference</text><text class="track-sub" x="6" y="${refLane0 + 25}">${esc(ref.id)}</text>`;
  s += `<text class="track-label" x="6" y="${qLane0 + 11}">Record</text><text class="track-sub" x="6" y="${qLane0 + 25}">${esc(rec.id)}</text>`;
  if (raws.length) s += `<text class="track-sub" x="6" y="${rawY + 7}">raw hit</text>`;
  if (isCDS) for (let l = 0; l < 3; l++) {
    s += `<text class="frame-label" x="${x0 - 6}" y="${refLane0 + l * (laneH + gap) + 12}" text-anchor="end">+${l + 1}</text>`;
    s += `<text class="frame-label" x="${x0 - 6}" y="${qLane0 + l * (laneH + gap) + 12}" text-anchor="end">+${l + 1}</text>`;
  }

  const step = niceStep(d1 - d0, x1 - x0, 95);
  const clampX = (v) => Math.max(x0, Math.min(x1, v));
  s += `<line class="backbone" x1="${r1(clampX(sx(1)))}" x2="${r1(clampX(sx(ref.length)))}" y1="${refAxisY}" y2="${refAxisY}"/>`;
  for (let t = Math.ceil(Math.max(d0, 1) / step) * step; t <= Math.min(d1, ref.length); t += step) {
    s += `<line class="tick" x1="${r1(sx(t))}" x2="${r1(sx(t))}" y1="${refAxisY - 4}" y2="${refAxisY}"/><text class="tick-label" x="${r1(sx(t))}" y="${refAxisY - 8}" text-anchor="middle">${fmtBp(t, step)}</text>`;
  }
  s += `<line class="backbone" x1="${r1(clampX(sx(1 + off)))}" x2="${r1(clampX(sx(G.len + off)))}" y1="${qAxisY}" y2="${qAxisY}"/>`;
  // Query ticks carry the record's own coordinates, even when it is drawn mirrored.
  for (let t = step; t <= G.len; t += step) {
    const x = sx(G.disp(t) + off);
    if (x < x0 - 1 || x > x1 + 1) continue;
    s += `<line class="tick" x1="${r1(x)}" x2="${r1(x)}" y1="${qAxisY}" y2="${qAxisY + 4}"/><text class="tick-label" x="${r1(x)}" y="${qAxisY + 15}" text-anchor="middle">${fmtBp(t, step)}</text>`;
  }

  s += `<g clip-path="url(#gm-clip)">`;
  s += `<rect class="track-band" x="${r1(sx(1))}" y="${refLane0 - 3}" width="${r1(Math.max(0, sx(ref.length) - sx(1)))}" height="${refBottom - refLane0 + 6}" rx="4"/>`;
  s += `<rect class="track-band" x="${r1(sx(1 + off))}" y="${qLane0 - 3}" width="${r1(Math.max(0, sx(G.len + off) - sx(1 + off)))}" height="${qBottom - qLane0 + 6}" rx="4"/>`;
  const ym = (ribTop + ribBot) / 2;
  feats.filter((f) => f.rs != null && f.qs != null).forEach((f) => {
    const [qa, qb] = G.span(f.qs, f.qe);
    const a1 = r1(sx(f.rs)), b1 = r1(sx(f.re + 1)), a2 = r1(sx(qa + off)), b2 = r1(sx(qb + 1 + off));
    s += `<path class="rib tone-${esc(toneOf(f))}${sel === f.name ? " is-selected" : ""}" d="M${a1},${ribTop}C${a1},${ym} ${a2},${ym} ${a2},${ribBot}L${b2},${ribBot}C${b2},${ym} ${b1},${ym} ${b1},${ribTop}Z" data-gene="${esc(f.name)}" data-tip="feat|${f.i}"/>`;
  });
  refItems.forEach((it) => {
    const g = it.g, name = g[0], f = byName[name], y = refLane0 + it.lane * (laneH + gap);
    const state = !f ? " is-absent" : keyOf(f) === "no_hit" ? " is-nohit" : keyOf(f) === "not_in_sequence" ? " is-absent" : "";
    const xa = sx(g[1]), xb = sx(g[2] + 1);
    s += `<path class="r-gene${state}${sel === name ? " is-selected" : ""}" d="${arrowPath(xa, xb, y, laneH, g[3])}" data-gene="${esc(name)}" data-tip="${f ? `feat|${f.i}` : `ref|${esc(name)}`}"/>`;
    if (fits(g[4], xb - xa)) s += `<text class="r-label" x="${r1((xa + xb) / 2)}" y="${y + 12.5}" text-anchor="middle" data-gene="${esc(name)}">${esc(g[4])}</text>`;
  });
  qItems.forEach((it) => {
    const f = it.f, y = qLane0 + it.lane * (laneH + gap), extra = f.rs == null;
    const xa = sx(it.s + off), xb = sx(it.e + 1 + off);
    const strand = G.flip ? (f.strand === "-" ? "+" : "-") : f.strand;
    const tone = toneOf(f);
    s += `<path class="q-gene tone-${esc(tone)}${extra ? " is-extra" : ""}${sel === f.name ? " is-selected" : ""}" d="${arrowPath(xa, xb, y, laneH, strand)}" data-gene="${esc(f.name)}" data-tip="feat|${f.i}"/>`;
    if (fits(f.label, xb - xa)) s += `<text class="q-label${extra || tone === "neutral" ? " is-extra" : ""}" x="${r1((xa + xb) / 2)}" y="${y + 12.5}" text-anchor="middle" data-gene="${esc(f.name)}">${esc(f.label)}</text>`;
    if (f.short) s += `<path class="short-flag" d="M${r1(xb - 7)},${y}h7v7z" data-gene="${esc(f.name)}"/>`;
  });
  raws.forEach((f) => {
    const [a, b] = G.span(f.raws, f.rawe);
    const xa = sx(a + off), xb = sx(b + 1 + off);
    s += `<rect class="raw-hit${sel === f.name ? " is-selected" : ""}" x="${r1(xa)}" y="${rawY}" width="${r1(Math.max(2, xb - xa))}" height="${rawH}" rx="2" data-gene="${esc(f.name)}" data-tip="raw|${f.i}"/>`;
  });
  s += `</g>`;
  svgSize(svg, W, H);
  svg.innerHTML = s;
  root.gm.feats = feats;
}

// ── reference / picker ────────────────────────────────────────────────
function drawReference(svg, W, d, picked) {
  const ref = d.ref, refLen = ref.length;
  const x0 = 8, x1 = W - 8;
  const sx = (v) => x0 + ((v - 1) / Math.max(1, refLen - 1)) * (x1 - x0);
  const isCDS = ref.ftype === "CDS", base = isCDS ? 3 : 1;
  const items = packLanes(ref.genes.map((g) => ({ s: g[1], e: g[2], pref: frameOf(g[1], isCDS), g })), base);
  const nL = laneCount(items, base);
  const laneH = 18, gap = 5, labelRows = 2, labelTop = 30, laneTop = labelTop + labelRows * 14 + 8;
  const lanesBottom = laneTop + nL * (laneH + gap);
  const H = lanesBottom + (isCDS ? 16 : 4);
  const step = niceStep(refLen, x1 - x0, 100);
  let s = "";
  for (let t = step; t < refLen; t += step) s += `<line class="tick" x1="${r1(sx(t))}" x2="${r1(sx(t))}" y1="14" y2="18"/><text class="tick-label" x="${r1(sx(t))}" y="11" text-anchor="middle">${fmtBp(t, step)}</text>`;
  s += `<line class="backbone" x1="${r1(sx(1))}" x2="${r1(sx(refLen))}" y1="18" y2="18"/>`;
  const rowEnd = Array(labelRows).fill(-1e9);
  items.forEach((it) => {
    const g = it.g, name = g[0], y = laneTop + it.lane * (laneH + gap), xa = sx(g[1]), xb = sx(g[2] + 1);
    const on = picked ? picked.has(name) : null;
    const cls = picked ? (on ? "pick-on" : "pick-off") : "r-gene";
    const extra = picked ? ` data-pick="${esc(name)}" role="button" tabindex="0" aria-pressed="${on}"` : "";
    s += `<path class="${cls}" d="${arrowPath(xa, xb, y, laneH, g[3])}"${extra} data-tip="${picked ? "pick" : "ref"}|${esc(name)}"/>`;
    if (fits(g[4], xb - xa)) s += `<text class="${on ? "pick-label" : "r-label"}" x="${r1((xa + xb) / 2)}" y="${y + 12.5}" text-anchor="middle">${esc(g[4])}</text>`;
    else {
      const mx = (xa + xb) / 2, w = String(g[4]).length * 6.4;
      let row = rowEnd.findIndex((e) => mx - w / 2 > e + 4);
      if (row < 0) row = rowEnd.indexOf(Math.min(...rowEnd));
      rowEnd[row] = mx + w / 2;
      const ly = labelTop + row * 14 + 10;
      s += `<line class="leader" x1="${r1(mx)}" x2="${r1(mx)}" y1="${ly + 3}" y2="${y}"/><text class="p-label" x="${r1(mx)}" y="${ly}" text-anchor="middle">${esc(g[4])}</text>`;
    }
  });
  if (isCDS) s += `<text class="frame-label" x="${x1}" y="${lanesBottom + 8}" text-anchor="end">lanes: reading frame +1 / +2 / +3</text>`;
  svgSize(svg, W, H);
  svg.innerHTML = s;
}

function drawPicker(svg, foot, W, d) {
  const picked = new Set(d.selected || []);
  drawReference(svg, W, d, picked);
  foot.hidden = false;
  const seen = new Set();
  foot.innerHTML = d.ref.genes.filter((g) => !seen.has(g[0]) && seen.add(g[0])).map((g) =>
    `<button type="button" class="chip${picked.has(g[0]) ? " is-on" : ""}" data-pick="${esc(g[0])}" aria-pressed="${picked.has(g[0])}"><b>${esc(g[4])}</b> ${nf((d.counts || {})[g[0]] || 0)}</button>`
  ).join("");
}

// ── evidence ──────────────────────────────────────────────────────────
function drawEvidence(svg, W, d) {
  const [a, b, label] = d.span;
  const genes = d.genes.map((g) => ({ name: g[0], start: g[1], end: g[2], strand: g[3] }));
  const touched = genes.filter((g) => g.end >= a && g.start <= b);
  let lo = Math.min(a, ...touched.map((g) => g.start)), hi = Math.max(b, ...touched.map((g) => g.end));
  const pad = Math.max((hi - lo) * 0.35, 120);
  lo = Math.max(1 - pad * 0.2, lo - pad); hi = hi + pad;
  const x0 = 6, x1 = W - 6, sx = (v) => x0 + ((v - lo) / (hi - lo)) * (x1 - x0);
  const items = packLanes(genes.filter((g) => g.end >= lo && g.start <= hi).map((g) => ({ s: g.start, e: g.end, pref: 0, g })), 1);
  const used = [...new Set(items.map((i) => i.lane))].sort((p, q) => p - q);
  const laneH = 16, gap = 4, top = 8;
  const refBottom = top + Math.max(1, used.length) * (laneH + gap) - gap;
  const annY = refBottom + 30, H = annY + 34;
  const hl = new Set(d.highlight || []);
  let s = `<path class="anno-shade" d="M${r1(sx(a))},${refBottom + 2}L${r1(sx(b + 1))},${refBottom + 2}L${r1(sx(b + 1))},${annY}L${r1(sx(a))},${annY}Z"/>`;
  items.forEach((it) => {
    const g = it.g, y = top + used.indexOf(it.lane) * (laneH + gap);
    const xa = Math.max(x0, sx(g.start)), xb = Math.min(x1, sx(g.end + 1));
    s += `<path class="r-gene${hl.has(g.name) ? " is-hit" : ""}" d="${arrowPath(xa, xb, y, laneH, g.strand)}" data-tip="lift|${esc(g.name)}|${g.start}|${g.end}"/>`;
    if (fits(g.name, xb - xa)) s += `<text class="r-label" x="${r1((xa + xb) / 2)}" y="${y + 11.5}" text-anchor="middle">${esc(g.name)}</text>`;
  });
  if (!items.length) s += `<text class="empty" x="${W / 2}" y="${top + 12}" text-anchor="middle">No reference gene was placed on ${esc(d.record.id)}.</text>`;
  s += `<rect class="anno-bar" x="${r1(sx(a))}" y="${annY}" width="${r1(Math.max(2, sx(b + 1) - sx(a)))}" height="10" rx="2" data-tip="span"/>`;
  const text = `${label} · ${nf(a)}–${nf(b)} · ${nf(b - a + 1)} nt on ${d.record.id}`;
  const lx = Math.min(Math.max(sx(a), x0), Math.max(x0, x1 - text.length * 6.2));
  s += `<text class="p-label" x="${r1(lx)}" y="${annY + 24}">${esc(text)}</text>`;
  svgSize(svg, W, H);
  svg.innerHTML = s;
}

// ── tooltip ───────────────────────────────────────────────────────────
function tipHtml(root, spec) {
  const d = root.gm.data, parts = spec.split("|");
  const row = (k, v) => `<div class="r"><span>${k}</span><span>${v}</span></div>`;
  const badge = (si) => { const [, l, t] = statusOf(d, si); return `<span class="badge tone-${esc(t)}">${esc(l)}</span>`; };
  if (parts[0] === "ref" || parts[0] === "pick") {
    const g = d.ref.genes.find((x) => x[0] === parts[1]);
    if (!g) return "";
    return `<div class="t">${esc(g[4])}</div>${row("reference", `${nf(g[1])}–${nf(g[2])}`)}${row("length", nf(g[2] - g[1] + 1) + " nt")}` +
      (parts[0] === "pick" ? row("sequences", nf((d.counts || {})[g[0]] || 0)) : "");
  }
  if (parts[0] === "lift") return `<div class="t">${esc(parts[1])}</div>${row("lifted to", `${nf(+parts[2])}–${nf(+parts[3])}`)}`;
  if (parts[0] === "span") { const [a, b, label] = d.span; return `<div class="t">${esc(label)}</div>${row("annotated", `${nf(a)}–${nf(b)}`)}`; }
  if (parts[0] === "cell") {
    const r = d.rows[+parts[1]], cell = r[2][+parts[2]], name = d.columns[+parts[2]];
    const g = d.ref.genes.find((x) => x[0] === name);
    return `<div class="t">${esc(g ? g[4] : name)} · <span class="sub">${esc(r[0])}</span></div><div>${badge(cell[0])}</div>` +
      (cell[1] != null ? row("record", `${nf(cell[1])}–${nf(cell[2])} · ${nf(cell[2] - cell[1] + 1)} nt`) : "") +
      (g ? row("reference", `${nf(g[1])}–${nf(g[2])} · ${nf(g[2] - g[1] + 1)} nt`) : "") +
      (cell[3] != null ? row("coverage", pct(cell[3], 1)) : "") + (cell[4] != null ? row("identity", cell[4].toFixed(1) + "%") : "") +
      (cell[5] && cell[1] != null && g ? `<div class="warn">${pct((cell[2] - cell[1] + 1) / (g[2] - g[1] + 1))} of the reference length</div>` : "");
  }
  if (parts[0] === "extra") {
    const r = d.rows[+parts[1]];
    return `<div class="t">${esc(r[0])}</div><div>Annotated names with no reference gene:</div>` +
      r[3].map((x) => row(esc(x[0]), x[2] != null ? `${nf(x[2])}–${nf(x[3])}` : esc(statusOf(d, x[1])[1]))).join("");
  }
  const f = (root.gm.feats || [])[+parts[1]];
  if (!f) return "";
  if (parts[0] === "raw") return `<div class="t">${esc(f.label)} · raw hit</div>${row("raw tblastn hit", `${nf(f.raws)}–${nf(f.rawe)}`)}${row("final CDS", `${nf(f.qs)}–${nf(f.qe)}`)}${f.rescue ? row("rescue", esc(f.rescue)) : ""}`;
  return `<div class="t">${esc(f.label)}</div><div>${badge(f.si)} <span class="sub">${esc(f.method)}</span></div>` +
    (f.qs != null ? row("record", `${nf(f.qs)}–${nf(f.qe)} · ${nf(f.qe - f.qs + 1)} nt`) : "") +
    (f.rs != null ? row("reference", `${nf(f.rs)}–${nf(f.re)} · ${nf(f.re - f.rs + 1)} nt`) : "") +
    (f.qs != null && f.cov != null ? row("coverage", pct(f.cov, 1)) : "") + (f.ident != null ? row("identity", f.ident.toFixed(1) + "%") : "") +
    (f.short ? `<div class="warn">${pct((f.qe - f.qs + 1) / (f.re - f.rs + 1))} of the reference length</div>` : "");
}

function showTip(root, e) {
  const tip = root.querySelector(".gm-tip");
  const t = e.target.closest && e.target.closest("[data-tip]");
  const html = t ? tipHtml(root, t.dataset.tip) : "";
  if (!html) { tip.hidden = true; return; }
  tip.innerHTML = html;
  tip.hidden = false;
  const box = root.getBoundingClientRect(), pad = 14;
  let x = e.clientX - box.left + pad, y = e.clientY - box.top + pad;
  if (x + tip.offsetWidth > box.width) x = Math.max(0, e.clientX - box.left - tip.offsetWidth - pad);
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}

// ── interaction ───────────────────────────────────────────────────────
function setView(root, v) {
  const g = root.gm.geom;
  if (!g) return;
  const [f0, f1] = g.full;
  const span = Math.max(60, Math.min(f1 - f0, v[1] - v[0]));
  let a = v[0] + (v[1] - v[0] - span) / 2;
  a = Math.max(f0, Math.min(f1 - span, a));
  root.gm.views[g.key] = [a, a + span];
  if (!root.gm.frame) root.gm.frame = requestAnimationFrame(() => { root.gm.frame = null; draw(root); });
}
function zoomAt(root, bp, factor) {
  const g = root.gm.geom, [d0, d1] = root.gm.views[g.key];
  const span = (d1 - d0) * factor, a = bp - (bp - d0) * factor;
  setView(root, [a, a + span]);
}
function clientToBp(root, e) {
  const g = root.gm.geom, [d0, d1] = root.gm.views[g.key];
  const box = root.querySelector(".gm-svg").getBoundingClientRect();
  return d0 + ((e.clientX - box.left - g.x0) / (g.x1 - g.x0)) * (d1 - d0);
}
function emit(root, event, value) {
  root.querySelector(".gm-tip").hidden = true;
  if (root.gm.emit) root.gm.emit(event, value);
}

function activate(root, el) {
  const d = root.gm.data;
  if (el.dataset.align) { root.gm.align = el.dataset.align; draw(root); return true; }
  if (el.dataset.zoom) {
    const g = root.gm.geom, [a, b] = root.gm.views[g.key];
    if (el.dataset.zoom === "fit") setView(root, g.full.slice());
    else zoomAt(root, (a + b) / 2, el.dataset.zoom === "in" ? 0.5 : 2);
    return true;
  }
  if (el.dataset.pick) { emit(root, "pick", el.dataset.pick); return true; }
  if (d.view === "matrix") {
    if (el.dataset.focus) { emit(root, "focus", el.dataset.focus); return true; }
    const row = el.closest("[data-rec]");
    if (row) {
      const cell = el.closest("[data-gene]");
      emit(root, "select", { record: row.dataset.rec, gene: cell ? cell.dataset.gene : null });
      return true;
    }
  }
  if (d.view === "tracks" && el.dataset.gene) { emit(root, "select", el.dataset.gene); return true; }
  return false;
}

function wire(root) {
  const svg = root.querySelector(".gm-svg");
  root.querySelector(".gm-matrix").addEventListener("scroll", () => { root.querySelector(".gm-tip").hidden = true; }, { passive: true });
  root.addEventListener("click", (e) => {
    if (root.gm.data.view === "tracks" && e.target.closest(".gm-svg")) return; // handled on pointerup
    const el = e.target.closest("[data-align],[data-zoom],[data-pick],[data-focus],[data-rec]");
    if (el) activate(root, el);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const el = e.target.closest("[data-pick],[data-focus],[data-rec],[data-gene]");
    if (el && activate(root, el)) e.preventDefault();
  });
  root.addEventListener("pointermove", (e) => {
    const gm = root.gm;
    if (gm.drag) {
      const dx = e.clientX - gm.drag.x;
      if (!gm.drag.moved && Math.abs(dx) > 4) { gm.drag.moved = true; svg.setPointerCapture(gm.drag.id); svg.classList.add("is-panning"); root.querySelector(".gm-tip").hidden = true; }
      if (gm.drag.moved) {
        const bpPerPx = (gm.drag.view[1] - gm.drag.view[0]) / (gm.geom.x1 - gm.geom.x0);
        setView(root, [gm.drag.view[0] - dx * bpPerPx, gm.drag.view[1] - dx * bpPerPx]);
      }
      return;
    }
    showTip(root, e);
    if (gm.data.view !== "tracks") return;
    const g = e.target.closest && e.target.closest("[data-gene]");
    const name = g ? g.dataset.gene : null;
    if (name !== gm.hover) {
      gm.hover = name;
      svg.querySelectorAll("[data-gene]").forEach((n) => n.classList.toggle("dim", !!name && n.dataset.gene !== name));
    }
  });
  root.addEventListener("pointerleave", () => {
    root.querySelector(".gm-tip").hidden = true;
    if (!root.gm.drag) { root.gm.hover = null; svg.querySelectorAll(".dim").forEach((n) => n.classList.remove("dim")); }
  });
  svg.addEventListener("pointerdown", (e) => {
    if (root.gm.data.view !== "tracks" || e.button !== 0) return;
    root.gm.drag = { x: e.clientX, view: root.gm.views[root.gm.geom.key].slice(), moved: false, id: e.pointerId };
  });
  const end = (e) => {
    const drag = root.gm.drag;
    if (!drag) return;
    if (!drag.moved && e.type === "pointerup") {
      const el = e.target.closest && e.target.closest("[data-gene]");
      if (el) activate(root, el);
    }
    if (drag.moved) { try { svg.releasePointerCapture(drag.id); } catch (_) { /* already released */ } }
    root.gm.drag = null;
    svg.classList.remove("is-panning");
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("wheel", (e) => {
    if (root.gm.data.view !== "tracks" || !(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoomAt(root, clientToBp(root, e), Math.exp(e.deltaY * 0.0025));
  }, { passive: false });
  svg.addEventListener("dblclick", (e) => {
    if (root.gm.data.view === "tracks") zoomAt(root, clientToBp(root, e), e.shiftKey ? 2 : 0.5);
  });
}
