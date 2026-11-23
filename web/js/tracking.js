// MadHearts web — riconoscimento del corpo con MediaPipe Pose (versione per browser).
// Stessa logica dell'app per Mac (madhearts/tracking.py):
// - i lati "left"/"right" sono ANATOMICI (braccio sinistro/destro della persona);
// - il riconoscimento lavora sull'immagine non specchiata, lo specchio si applica
//   solo alle coordinate in uscita (così il modello non confonde destra e sinistra);
// - un punto sul bordo dell'immagine, o fuori, è considerato non visibile.
// Coordinate in uscita: 0..1, x verso destra, y verso il basso.

import { FilesetResolver, PoseLandmarker } from "../vendor/mediapipe/vision_bundle.mjs";

import { SIDES } from "./common.js";
export { SIDES };
const IDX = { shoulder: [11, 12], elbow: [13, 14], wrist: [15, 16], pinky: [17, 18], index: [19, 20], thumb: [21, 22], hip: [23, 24] };

export class Tracker {
  static async create(cfg, base = ".") {
    const t = new Tracker(cfg);
    const fileset = await FilesetResolver.forVisionTasks(`${base}/vendor/mediapipe/wasm`);
    const opts = (delegate) => ({
      baseOptions: { modelAssetPath: `${base}/models/pose_landmarker_${cfg.tracking.pose_model}.task`, delegate },
      runningMode: "VIDEO",
      numPoses: 1,
      minPoseDetectionConfidence: cfg.tracking.min_detection_confidence,
      minPosePresenceConfidence: cfg.tracking.min_presence_confidence,
      minTrackingConfidence: cfg.tracking.min_tracking_confidence,
    });
    try {
      t.pose = await PoseLandmarker.createFromOptions(fileset, opts(cfg.tracking.delegate));
      t.delegate = cfg.tracking.delegate;
    } catch (e) {
      console.warn("delegate", cfg.tracking.delegate, "non disponibile, uso la CPU", e);
      t.pose = await PoseLandmarker.createFromOptions(fileset, opts("CPU"));
      t.delegate = "CPU";
    }
    return t;
  }

  constructor(cfg) {
    this.configure(cfg);
    this.lastTs = 0;
  }

  configure(cfg) {
    this.mirror = cfg.camera.mirror;
    this.edge = cfg.tracking.edge_margin;
  }

  _pt(lm) {
    const x = this.mirror ? 1 - lm.x : lm.x;
    let vis = lm.visibility ?? 1;
    if (lm.presence !== undefined) vis = Math.min(vis, lm.presence);
    const m = this.edge;
    if (!(lm.x >= m && lm.x <= 1 - m && lm.y >= -0.02 && lm.y <= 1 - m)) vis = 0;   // fuori o sul bordo
    return { x, y: lm.y, z: lm.z ?? 0, visibility: vis };
  }

  // video: elemento <video>; restituisce un'osservazione nello stesso formato dell'app per Mac
  process(video, frameId) {
    let ts = performance.now();
    if (ts <= this.lastTs) ts = this.lastTs + 1;           // timestamp sempre crescenti
    this.lastTs = ts;
    const t0 = performance.now();
    const res = this.pose.detectForVideo(video, ts);
    const obs = {
      frameId, timestamp: ts / 1000, present: false, arms: {}, shoulderWidth: 0,
      aspect: video.videoWidth / video.videoHeight, poseMs: performance.now() - t0,
    };
    if (!res.landmarks || !res.landmarks.length) return obs;
    const L = res.landmarks[0];
    obs.present = true;
    SIDES.forEach((side, i) => {
      const arm = { side };
      for (const part of ["shoulder", "elbow", "wrist", "pinky", "index", "thumb"]) arm[part] = this._pt(L[IDX[part][i]]);
      obs.arms[side] = arm;
    });
    obs.hips = [this._pt(L[IDX.hip[0]]), this._pt(L[IDX.hip[1]])];
    const ls = obs.arms.left.shoulder, rs = obs.arms.right.shoulder;
    obs.shoulderWidth = Math.hypot((ls.x - rs.x) * obs.aspect, ls.y - rs.y) / obs.aspect;
    return obs;
  }

  close() {
    this.pose?.close();
  }
}
