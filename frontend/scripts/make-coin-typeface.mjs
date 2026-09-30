// Builds public/fonts/coin-b.typeface.json: a three.js typeface holding only the "B" the coin
// needs, cut from Fraunces (SIL OFL) so the embossed letter matches the display font.
//
// Input is a static Fraunces instance, e.g. from the variable font with fontTools:
//   python3 -c "from fontTools.ttLib import TTFont; from fontTools.varLib import instancer; \
//     instancer.instantiateVariableFont(TTFont('Fraunces[SOFT,WONK,opsz,wght].ttf'), \
//     {'wght':720,'opsz':72,'SOFT':50,'WONK':0}).save('Fraunces-Coin.ttf')"
// Usage: node scripts/make-coin-typeface.mjs Fraunces-Coin.ttf
//
// Fraunces draws the B's two counters as one self-crossing keyhole contour, which three.js fills.
// Resolve it first with skia-pathops (even-odd simplify), e.g.:
//   p = pathops.Path(); glyphSet['B'].draw(p.getPen()); p.fillType = pathops.FillType.EVEN_ODD
//   p.simplify(fix_winding=True)   # then write it back with TTGlyphPen
// This script then winds every contour by nesting depth: even = solid (clockwise, as three
// expects), odd = hole (counter-clockwise).
import { readFileSync, writeFileSync } from "node:fs";
import opentype from "opentype.js";

const src = process.argv[2];
if (!src) throw new Error("usage: node scripts/make-coin-typeface.mjs <font.ttf>");
const buf = readFileSync(src);
const font = opentype.parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
const r = (n) => Math.round(n);

/** split opentype path commands into contours of segments */
function contours(commands) {
  const out = [];
  let cur = null;
  for (const c of commands) {
    if (c.type === "M") {
      cur = { start: [c.x, c.y], segs: [] };
      out.push(cur);
    } else if (c.type === "L") cur.segs.push({ type: "L", to: [c.x, c.y] });
    else if (c.type === "Q") cur.segs.push({ type: "Q", c1: [c.x1, c.y1], to: [c.x, c.y] });
    else if (c.type === "C") cur.segs.push({ type: "C", c1: [c.x1, c.y1], c2: [c.x2, c.y2], to: [c.x, c.y] });
  }
  return out;
}

function points(ct) {
  const pts = [ct.start];
  for (const s of ct.segs) {
    if (s.c1) pts.push(s.c1);
    if (s.c2) pts.push(s.c2);
    pts.push(s.to);
  }
  return pts;
}

/** shoelace; negative = clockwise in y-up font units */
function area(ct) {
  const p = points(ct);
  let a = 0;
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i];
    const [x2, y2] = p[(i + 1) % p.length];
    a += x1 * y2 - x2 * y1;
  }
  return a / 2;
}

function reverse(ct) {
  const nodes = [ct.start, ...ct.segs.map((s) => s.to)];
  const segs = [];
  for (let i = ct.segs.length - 1; i >= 0; i--) {
    const s = ct.segs[i];
    const to = nodes[i];
    if (s.type === "L") segs.push({ type: "L", to });
    else if (s.type === "Q") segs.push({ type: "Q", c1: s.c1, to });
    else segs.push({ type: "C", c1: s.c2, c2: s.c1, to });
  }
  return { start: nodes[nodes.length - 1], segs };
}

function inside([px, py], ct) {
  const p = points(ct);
  let hit = false;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i];
    const [xj, yj] = p[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

const glyphs = {};
for (const ch of ["B"]) {
  const g = font.charToGlyph(ch);
  // nesting depth decides solid vs hole: even = solid (clockwise), odd = hole
  const cts = contours(g.path.commands).map((ct, i, all) => {
    const depth = all.filter((other, j) => j !== i && inside(ct.start, other)).length;
    const wantClockwise = depth % 2 === 0;
    return area(ct) < 0 === wantClockwise ? ct : reverse(ct);
  });
  // typeface.js order: q = end, control; b = end, control1, control2
  const o = cts
    .flatMap((ct) => [
      `m ${r(ct.start[0])} ${r(ct.start[1])}`,
      ...ct.segs.map((s) =>
        s.type === "L"
          ? `l ${r(s.to[0])} ${r(s.to[1])}`
          : s.type === "Q"
            ? `q ${r(s.to[0])} ${r(s.to[1])} ${r(s.c1[0])} ${r(s.c1[1])}`
            : `b ${r(s.to[0])} ${r(s.to[1])} ${r(s.c1[0])} ${r(s.c1[1])} ${r(s.c2[0])} ${r(s.c2[1])}`,
      ),
    ])
    .join(" ");
  const bb = g.getBoundingBox();
  glyphs[ch] = { ha: r(g.advanceWidth), x_min: r(bb.x1), x_max: r(bb.x2), o };
}

const out = {
  glyphs,
  familyName: "Fraunces",
  ascender: r(font.ascender),
  descender: r(font.descender),
  underlinePosition: r(font.tables.post.underlinePosition),
  underlineThickness: r(font.tables.post.underlineThickness),
  boundingBox: { yMin: r(font.tables.head.yMin), xMin: r(font.tables.head.xMin), yMax: r(font.tables.head.yMax), xMax: r(font.tables.head.xMax) },
  resolution: font.unitsPerEm,
  original_font_information: { format: 0, copyright: "Fraunces, SIL Open Font License 1.1" },
  cssFontWeight: "normal",
  cssFontStyle: "normal",
};
writeFileSync("public/fonts/coin-b.typeface.json", JSON.stringify(out));
console.log("wrote public/fonts/coin-b.typeface.json");
