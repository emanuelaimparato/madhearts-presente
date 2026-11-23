// MadHearts web — regolazioni: gli stessi parametri del pannello dell'app per Mac.
// Ogni modifica (da pulsanti, tastiera o pannello) viene salvata subito in questo browser
// e prevale sui valori predefiniti anche ai prossimi avvii.

const KEY = "madhearts.impostazioni.v1";

// id "sezione.chiave", etichetta, gruppo, min, max, passo, unità, nota
export const PARAMS = [
  ["audio.master_volume", "Volume generale", "Audio", 0, 1, 0.05, "%", ""],
  ["audio.music_volume", "Musica", "Audio", 0, 1, 0.05, "%", ""],
  ["audio.ambient_volume", "Tappeto sonoro", "Audio", 0, 1, 0.05, "%", ""],
  ["audio.trail_volume", "Suono della scia", "Audio", 0, 1, 0.05, "%", ""],
  ["audio.chime_volume", "Rintocco del nuovo anello", "Audio", 0, 1, 0.05, "%", ""],
  ["visuals.exposure", "Luminosità", "Esperienza", 0.3, 3, 0.05, "", ""],
  ["visuals.response_intensity", "Intensità della risposta ai gesti", "Esperienza", 0.2, 2.5, 0.05, "", ""],
  ["visuals.filament_length", "Durata della scia", "Esperienza", 0.5, 8, 0.1, "s", ""],
  ["visuals.fade_speed", "Velocità di dissolvenza", "Esperienza", 0.2, 3, 0.05, "", ""],
  ["tracking.min_visibility", "Soglia di rilevamento", "Esperienza", 0.05, 0.9, 0.05, "", "più bassa = più sensibile (anche con poca luce)"],
  ["motion.session_rest_seconds", "Braccia a riposo per completare il filo", "Sfera", 1, 30, 1, "s", ""],
  ["visuals.sphere_rotation_speed", "Velocità di rotazione della sfera", "Sfera", 0, 0.3, 0.005, "", ""],
  ["visuals.ring_brightness", "Luminosità degli anelli", "Sfera", 0.1, 1.5, 0.05, "", ""],
  ["visuals.sphere_radius", "Grandezza della sfera", "Sfera", 0.1, 0.5, 0.01, "", ""],
  ["attract.invite_opacity", "Invito", "Schermata d'attesa", 0, 1, 0.05, "%", "0 = nascosto"],
  ["attract.logo_opacity", "Logo", "Schermata d'attesa", 0, 1, 0.05, "%", "0 = nascosto"],
];
export const PARAM = Object.fromEntries(PARAMS.map((p) => [p[0], p]));

export function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    return Object.fromEntries(Object.entries(raw).filter(([k, v]) => PARAM[k] && typeof v === "number"));
  } catch (e) {
    return {};
  }
}

export function saveSettings(overrides) {
  try { localStorage.setItem(KEY, JSON.stringify(overrides)); } catch (e) { /* navigazione privata: valgono solo per ora */ }
}

export function clearSettings() {
  try { localStorage.removeItem(KEY); } catch (e) { /* niente da fare */ }
}

// converte {"audio.master_volume": 0.6, ...} in {audio: {master_volume: 0.6}, ...}
export function toConfig(overrides) {
  const out = {};
  for (const [id, v] of Object.entries(overrides)) {
    const [sec, key] = id.split(".");
    (out[sec] ||= {})[key] = v;
  }
  return out;
}

export function clampParam(id, v) {
  const [, , , lo, hi, step] = PARAM[id];
  return Math.round(Math.min(Math.max(v, lo), hi) / step) * step;
}

export function formatParam(id, v) {
  const unit = PARAM[id][6];
  if (unit === "%") return Math.round(v * 100) + "%";
  if (unit === "s") return v.toFixed(1) + " s";
  return v.toFixed(2);
}
