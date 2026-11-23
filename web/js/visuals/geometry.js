// MadHearts web — geometria dei nastri (traduzione di _normals, _strip e _resample di engine.py).
// Vertici: 9 float = x y r g b a v u dry  (v attraverso il nastro -1..1, u lungo il nastro).

export const FLOATS = 9;

export function normals(pts, aspect) {
  const m = pts.length, out = new Array(m);
  for (let i = 0; i < m; i++) {
    const a = pts[Math.max(i - 1, 0)], b = pts[Math.min(i + 1, m - 1)];
    const div = i === 0 || i === m - 1 ? 1 : 2;                 // come np.gradient
    let tx = ((b[0] - a[0]) * aspect) / div, ty = (b[1] - a[1]) / div;
    const l = Math.hypot(tx, ty);
    if (l > 1e-9) { tx /= l; ty /= l; } else { tx = 1; ty = 0; }
    out[i] = [-ty, tx];
  }
  return out;
}

// line: [[x,y],...] in uv (y in alto); width, alpha, dry: numero o array; cols: [[r,g,b],...] o [r,g,b]
export function strip(out, line, width, cols, alpha, aspect, { u = null, dry = 0, uOffset = 0, uScale = 1 } = {}) {
  const m = line.length;
  if (m < 2) return;
  const at = (v, i) => (typeof v === "number" ? v : v[i]);
  const colAt = (i) => (typeof cols[0] === "number" ? cols : cols[i]);
  let uu = u;
  if (!uu) {
    uu = new Array(m);
    uu[0] = uOffset;
    for (let i = 1; i < m; i++) uu[i] = uu[i - 1] + Math.hypot((line[i][0] - line[i - 1][0]) * aspect, line[i][1] - line[i - 1][1]) * uScale;
  }
  const nrm = normals(line, aspect);
  const L = [], R = [];
  for (let i = 0; i < m; i++) {
    const h = at(width, i) / 2, nx = nrm[i][0] / aspect, ny = nrm[i][1];
    L.push([line[i][0] + nx * h, line[i][1] + ny * h]);
    R.push([line[i][0] - nx * h, line[i][1] - ny * h]);
  }
  const vert = (p, i, v) => {
    const c = colAt(i);
    out.push(p[0], p[1], c[0], c[1], c[2], at(alpha, i), v, uu[i], at(dry, i));
  };
  for (let i = 0; i < m - 1; i++) {
    vert(L[i], i, 1); vert(R[i], i, -1); vert(L[i + 1], i + 1, 1);
    vert(R[i], i, -1); vert(R[i + 1], i + 1, -1); vert(L[i + 1], i + 1, 1);
  }
}

// interpolazione lineare come np.interp (xs crescenti, anche con valori ripetuti)
export function interp(x, xs, ys) {
  const n = xs.length;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[n - 1]) return ys[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  const d = xs[hi] - xs[lo];
  return d > 0 ? ys[lo] + ((ys[hi] - ys[lo]) * (x - xs[lo])) / d : ys[hi];
}
