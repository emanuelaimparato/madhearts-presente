// MadHearts web — texture della pennellata, generata una volta (traduzione di _brush_texture):
// setole lungo il tratto, bordi sfrangiati, grana. Ripetibile lungo la lunghezza.

function rand(seed) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return { next, gauss: () => Math.sqrt(-2 * Math.log(next() + 1e-12)) * Math.cos(2 * Math.PI * next()) };
}

// rumore periodico (somma di onde con frequenze intere: si ripete senza giunture)
function pnoise(r, rows, w, cutoff) {
  const out = [];
  for (let k = 0; k < rows; k++) {
    const row = new Float32Array(w);
    for (let f = 1; f < cutoff; f++) {
      const a = r.gauss(), b = r.gauss(), step = (2 * Math.PI * f) / w;
      for (let x = 0; x < w; x++) row[x] += a * Math.cos(step * x) + b * Math.sin(step * x);
    }
    let sd = 0;
    for (const v of row) sd += v * v;
    sd = Math.sqrt(sd / w) + 1e-9;
    for (let x = 0; x < w; x++) row[x] /= sd;
    out.push(row);
  }
  return out;
}

export function brushTexture(w = 1024, h = 64, seed = 11) {
  const r = rand(seed);
  let br = pnoise(r, h, w, 48);
  for (let pass = 0; pass < 2; pass++) {                 // setole a ciuffi
    const next = br.map((row) => row.slice());
    for (let y = 1; y < h - 1; y++) for (let x = 0; x < w; x++) next[y][x] = 0.25 * br[y - 1][x] + 0.5 * br[y][x] + 0.25 * br[y + 1][x];
    br = next;
  }
  let sd = 0;
  for (const row of br) for (const v of row) sd += v * v;
  sd = Math.sqrt(sd / (w * h)) + 1e-9;
  const edge = pnoise(r, 1, w, 14)[0];
  const data = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const v = Math.abs(-1 + (2 * y) / (h - 1));
    for (let x = 0; x < w; x++) {
      const b = 0.5 + 0.5 * Math.tanh((br[y][x] / sd) * 1.1);
      let m = Math.min(Math.max((0.72 + 0.14 * edge[x] + 0.1 - v) / 0.2, 0), 1);
      m = m * m * (3 - 2 * m);
      const grain = 0.8 + 0.2 * r.next();
      data[y * w + x] = Math.round(Math.min(b * m * grain, 1) * 255);
    }
  }
  return { data, w, h };
}
