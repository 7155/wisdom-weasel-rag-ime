/** The cinematic cloud plate retains its authored light and ring silhouette.
 * Longitude advection is deliberately bounded: a single view cannot supply
 * the unseen hemisphere of a full rotation. */
export const STELLAR_PLANET_VERTEX = `
attribute vec2 a_position;
varying vec2 v_uv;
void main() {
  v_uv = vec2((a_position.x + 1.0) * .5, (1.0 - a_position.y) * .5);
  gl_Position = vec4(a_position, 0.0, 1.0);
}`;

export const STELLAR_PLANET_FRAGMENT = `
precision highp float;
uniform sampler2D u_image;
uniform float u_time;
uniform float u_keyBlack;
varying vec2 v_uv;
void main() {
  vec4 original = texture2D(u_image, v_uv);
  // The plate's globe and ring measurements are in 1536 x 1024 image space.
  vec2 p = (v_uv - vec2(.5, .491)) * vec2(1536.0, 1024.0) / 381.0;
  float radius = length(p);
  float z = sqrt(max(0.0, 1.0 - dot(p, p)));
  vec2 ring = vec2(.97 * p.x - .243 * p.y, .243 * p.x + .97 * p.y);
  float arc = .365 * sqrt(max(0.0, 1.0 - pow(ring.x / 1.93, 2.0)));
  float clearOfRing = smoothstep(.065, .24, abs(ring.y - arc));
  float interior = (1.0 - smoothstep(.75, .98, radius)) * clearOfRing;
  float longitude = .09 * sin(u_time * .014);
  vec2 uv = v_uv + vec2(.24, -.06) * longitude * z * interior;
  vec3 color = mix(original.rgb, texture2D(u_image, uv).rgb, interior);
  float alpha = original.a;
  if (u_keyBlack > .5) {
    // The export stage composites the supplied black-backed plate. The
    // opaque globe is retained; only the unlit exterior becomes transparent.
    alpha = max(max(original.r, original.g), original.b);
    alpha = max(alpha, 1.0 - smoothstep(.975, 1.0, radius));
    // The input light is already composited against black. Preserve those
    // premultiplied RGB values: multiplying by alpha again creates a soot rim.
    gl_FragColor = vec4(color, alpha);
    return;
  }
  gl_FragColor = vec4(color * alpha, alpha);
}`;
