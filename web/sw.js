// MadHearts web — funzionamento offline.
// Strategia "prima la rete": se il server risponde si usa sempre la versione più recente
// (gli aggiornamenti arrivano subito); se non risponde si usa la copia salvata.
// Alla prima apertura vengono salvati tutti i file necessari, modelli compresi.

const CACHE = "madhearts-v2";
const FILES = [
  "./", "index.html", "telecomando.html", "manifest.webmanifest", "sw.js",
  "js/config.js", "js/common.js", "js/camera.js", "js/tracking.js", "js/motion.js", "js/simulate.js", "js/audio.js", "js/settings.js", "js/remote-host.js",
  "js/visuals/gl.js", "js/visuals/geometry.js", "js/visuals/brush.js", "js/visuals/sphere.js", "js/visuals/engine.js", "js/visuals/attract.js",
  "vendor/mediapipe/vision_bundle.mjs", "vendor/mediapipe/wasm/vision_wasm_internal.js", "vendor/mediapipe/wasm/vision_wasm_internal.wasm",
  "vendor/peerjs/peerjs.min.js", "vendor/qrcode/qrcode.mjs",
  "models/pose_landmarker_full.task",
  "assets/logo.png", "assets/icona.png", "assets/fonts/LeagueGothic.ttf", "assets/fonts/DMSans.ttf",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true }).then((r) => r || Response.error()))
  );
});
