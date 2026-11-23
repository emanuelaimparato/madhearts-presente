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
    // nella pagina ma invisibile: alcuni browser segnalano i fotogrammi solo per video presenti nel documento
    Object.assign(this.video.style, { position: "fixed", left: "0", top: "0", width: "2px", height: "2px", opacity: "0.01", pointerEvents: "none" });
    document.body.appendChild(this.video);
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
    // Ogni fotogramma VERO della camera: requestVideoFrameCallback (Chrome, Safari 15.4+).
    // L'orologio del video (currentTime) in alcuni browser avanza anche tra un fotogramma e
    // l'altro, e farebbe analizzare più volte lo stesso fotogramma.
    this.fresh = false;
    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
      const onFrame = () => {
        this.fresh = true;
        if (this.stream) this.video.requestVideoFrameCallback(onFrame);
      };
      this.video.requestVideoFrameCallback(onFrame);
      this.useCallback = true;
    }
    const s = this.stream.getVideoTracks()[0].getSettings();
    this.settings = { width: s.width, height: s.height, fps: s.frameRate, label: this.stream.getVideoTracks()[0].label };
    return this;
  }

  // true se è arrivato un fotogramma nuovo dall'ultima chiamata
  newFrame() {
    if (this.video.readyState < 2) return false;
    if (this.useCallback) {
      if (!this.fresh) return false;
      this.fresh = false;
    } else {
      const t = this.video.currentTime;
      if (t === this.lastVideoTime) return false;
      this.lastVideoTime = t;
    }
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
    this.video.remove();
  }
}
