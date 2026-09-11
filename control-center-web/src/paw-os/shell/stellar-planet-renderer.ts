import { STELLAR_PLANET_FRAGMENT, STELLAR_PLANET_VERTEX } from './stellar-planet-material';

export type StellarPlanetRenderer = {
  setPaused: (paused: boolean) => void;
  resize: () => void;
  dispose: () => void;
};

/** Single quad, capped backing store, 24 material frames/sec, no React frame
 * state. Suspension cancels RAF rather than spinning a hidden render loop. */
export function createStellarPlanetRenderer(
  canvas: HTMLCanvasElement,
  source: HTMLImageElement,
  onUnavailable: () => void,
  keyBlack = false,
): StellarPlanetRenderer | null {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: false, depth: false, stencil: false, powerPreference: 'low-power' });
  if (!gl) return null;
  const shaders: WebGLShader[] = [];
  let program: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  let texture: WebGLTexture | null = null;
  let frame = 0;
  let lastFrame: number | null = null;
  let elapsed = 0;
  let paused = true;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', contextLost);
    gl.deleteTexture(texture);
    gl.deleteBuffer(buffer);
    gl.deleteProgram(program);
    shaders.forEach((shader) => gl.deleteShader(shader));
  };
  const contextLost = (event: Event) => {
    event.preventDefault();
    dispose();
    onUnavailable();
  };
  try {
    const compile = (type: number, sourceCode: string) => {
      const shader = gl.createShader(type);
      if (!shader) throw new Error('Planet shader unavailable');
      shaders.push(shader);
      gl.shaderSource(shader, sourceCode);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Planet shader unsupported');
      return shader;
    };
    program = gl.createProgram();
    buffer = gl.createBuffer();
    texture = gl.createTexture();
    if (!program || !buffer || !texture) throw new Error('Planet resources unavailable');
    gl.attachShader(program, compile(gl.VERTEX_SHADER, STELLAR_PLANET_VERTEX));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, STELLAR_PLANET_FRAGMENT));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Planet material unsupported');
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const time = gl.getUniformLocation(program, 'u_time');
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    gl.uniform1i(gl.getUniformLocation(program, 'u_image'), 0);
    gl.uniform1f(gl.getUniformLocation(program, 'u_keyBlack'), keyBlack ? 1 : 0);
    const paint = () => {
      if (disposed) return;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform1f(time, elapsed / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    const resize = () => {
      if (disposed) return;
      const width = Math.min(960, Math.max(1, Math.round(canvas.clientWidth * Math.min(window.devicePixelRatio || 1, 1.5))));
      const height = Math.round(width * 2 / 3);
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      paint();
    };
    const tick = (now: number) => {
      if (disposed || paused) return;
      if (lastFrame === null) lastFrame = now;
      if (now - lastFrame >= 1000 / 24) {
        elapsed += Math.min(now - lastFrame, 100);
        lastFrame = now;
        paint();
      }
      frame = requestAnimationFrame(tick);
    };
    canvas.addEventListener('webglcontextlost', contextLost);
    resize();
    return {
      resize,
      dispose,
      setPaused(next) {
        if (disposed || paused === next) return;
        paused = next;
        lastFrame = null;
        if (paused) cancelAnimationFrame(frame);
        else frame = requestAnimationFrame(tick);
      },
    };
  } catch {
    dispose();
    return null;
  }
}
