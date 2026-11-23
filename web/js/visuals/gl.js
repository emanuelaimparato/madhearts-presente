// MadHearts web — piccole utilità WebGL2: programmi, quadrato a schermo intero, texture e framebuffer.

export function createContext(canvas) {
  const gl = canvas.getContext("webgl2", { antialias: false, alpha: false, premultipliedAlpha: false, preserveDrawingBuffer: false, powerPreference: "high-performance" });
  if (!gl) throw new Error("Questo browser non supporta WebGL2: usa una versione recente di Chrome o Safari.");
  // rendering su texture in virgola mobile (luce senza scalini); se manca si usa 8 bit
  gl.floatTargets = !!gl.getExtension("EXT_color_buffer_float");
  gl.getExtension("OES_texture_float_linear");
  return gl;
}

export function program(gl, vs, fs) {
  const sh = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error("shader: " + gl.getShaderInfoLog(s) + "\n" + src);
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("programma: " + gl.getProgramInfoLog(p));
  const uniforms = {};
  const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) {
    const info = gl.getActiveUniform(p, i);
    uniforms[info.name.replace(/\[0\]$/, "")] = gl.getUniformLocation(p, info.name);
  }
  return { p, u: uniforms };
}

// imposta le uniform presenti (quelle eliminate dal compilatore vengono ignorate)
export function setUniforms(gl, prog, values) {
  for (const [k, v] of Object.entries(values)) {
    const loc = prog.u[k];
    if (loc === undefined || loc === null) continue;
    if (typeof v === "number") gl.uniform1f(loc, v);
    else if (v.int !== undefined) gl.uniform1i(loc, v.int);
    else if (v.length === 2) gl.uniform2f(loc, v[0], v[1]);
    else if (v.length === 3) gl.uniform3f(loc, v[0], v[1], v[2]);
    else if (v.length === 4) gl.uniform4f(loc, v[0], v[1], v[2], v[3]);
  }
}

export function fullscreenQuad(gl) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);
  return { draw: () => { gl.bindVertexArray(vao); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); } };
}

export function target(gl, w, h) {
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  if (gl.floatTargets) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, w, h, 0, gl.RGBA, gl.HALF_FLOAT, null);
  else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const fb = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  return { tex, fb, w, h, release: () => { gl.deleteTexture(tex); gl.deleteFramebuffer(fb); } };
}

export function bindTarget(gl, t) {
  gl.bindFramebuffer(gl.FRAMEBUFFER, t ? t.fb : null);
  if (t) gl.viewport(0, 0, t.w, t.h);
}

export function bindTex(gl, unit, tex) {
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, tex);
  return { int: unit };
}
