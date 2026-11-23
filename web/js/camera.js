// MadHearts web — acquisizione video dalla webcam.
// L'immagine resta solo in memoria: non viene mai salvata né inviata.

export async function listCameras() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === "videoinput");
}

export class Camera {
  constructor({ width = 1280, height = 720, fps = 30, deviceId = "" } = {}) {
    this.req = { width, height, fps, deviceId };
    this.video = document.createElement("video");
    this.video.playsInline = true;
    this.video.muted = true;
    this.stream = null;
    this.frameTimes = [];
    this.lastVideoTime = -1;
    this.frameId = 0;
  }

  async start() {
    const { width, height, fps, deviceId } = this.req;
    const video = {
      width: { ideal: width }, height: { ideal: height }, frameRate: { ideal: fps },
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    };
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (e) {
      if (e.name === "NotAllowedError") {
        throw new Error("Permesso della webcam negato: consentilo dall'icona della fotocamera nella barra degli indirizzi e ricarica la pagina.");
      }
      if (e.name === "NotFoundError") throw new Error("Nessuna webcam trovata.");
      if (e.name === "NotReadableError") throw new Error("La webcam è usata da un'altra app (FaceTime, Zoom, l'app per Mac di MadHearts...): chiudila e riprova.");
      throw e;
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    const s = this.stream.getVideoTracks()[0].getSettings();
    this.settings = { width: s.width, height: s.height, fps: s.frameRate, label: this.stream.getVideoTracks()[0].label };
    return this;
  }

  // true se è arrivato un fotogramma nuovo dall'ultima chiamata
  newFrame() {
    const t = this.video.currentTime;
    if (t === this.lastVideoTime || this.video.readyState < 2) return false;
    this.lastVideoTime = t;
    this.frameId++;
    const now = performance.now();
    this.frameTimes.push(now);
    while (this.frameTimes.length && now - this.frameTimes[0] > 2000) this.frameTimes.shift();
    return true;
  }

  fps() {
    const f = this.frameTimes;
    return f.length > 1 ? ((f.length - 1) * 1000) / (f[f.length - 1] - f[0]) : 0;
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }
}
