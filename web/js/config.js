// MadHearts web — configurazione predefinita (stessi valori di config.toml dell'app per Mac).
// Le regolazioni fatte dal pannello verranno salvate nel browser e prevarranno su questi valori.

export const DEFAULTS = {
  camera: { width: 1280, height: 720, fps: 30, mirror: true, deviceId: "" },
  tracking: {
    pose_model: "full",            // "lite" (più veloce) o "full" (più preciso)
    delegate: "GPU",               // "GPU" o "CPU" (se la GPU non è disponibile si passa alla CPU)
    min_detection_confidence: 0.5,
    min_presence_confidence: 0.5,
    min_tracking_confidence: 0.5,
    min_visibility: 0.3,
    edge_margin: 0.02,             // fascia ai bordi in cui un punto conta come fuori inquadratura
  },
};

export function deepMerge(base, extra) {
  const out = structuredClone(base);
  for (const [k, v] of Object.entries(extra || {})) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && typeof out[k] === "object" ? deepMerge(out[k], v) : v;
  }
  return out;
}
