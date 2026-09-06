// Painted stars use procedural ink-like strokes and an irregular warm core.
// They are abstract selection marks, not physically shaded planet spheres.
export const starVertex = `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }
`;
export const starFragment = `
  varying vec2 vUv; uniform vec3 uColor; uniform float uSelected; uniform float uTime; uniform float uWorking; uniform float uSeed;
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f*f*(3.-2.*f);
    return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y);
  }
  void main() {
    vec2 p = (vUv - .5) * 2.; float r = length(p); if (r > 1.) discard;
    float a = atan(p.y, p.x);
    float grain = noise(p * 26. + uSeed);
    float warped = r * (1. + .07*sin(a*3.+uSeed) + .04*sin(a*7.));
    float core = exp(-warped*warped*38.);
    float broken = .55+.45*sin(a*4.+uSeed-uTime*uWorking*.12);
    float rings = exp(-pow((warped-.34)*32.,2.))*.065 + exp(-pow((warped-.54)*40.,2.))*.035;
    rings *= (.5+grain*.5)*(.35+broken*.65);
    float halo = exp(-r*r*7.) * .09;
    float glint = (exp(-abs(p.x)*95.-abs(p.y)*7.) + exp(-abs(p.y)*95.-abs(p.x)*7.))*.22;
    float alpha = core * (.82+grain*.18) + rings*(1.+uSelected*2.) + halo + glint;
    alpha *= 1. - smoothstep(.75, 1., r);
    vec3 color = mix(uColor, vec3(1., .95, .76), core * .85);
    gl_FragColor = vec4(color, min(.98, alpha));
    #include <colorspace_fragment>
  }
`;
export const pointVertex = `
  attribute float aSize; attribute vec3 aColor; varying vec3 vColor;
  uniform float uRatio;
  void main() { vColor = aColor; vec4 view = modelViewMatrix * vec4(position, 1.);
    gl_Position = projectionMatrix * view; gl_PointSize = clamp(aSize * uRatio * 110. / max(4., -view.z), 1., 3.); }
`;
export const pointFragment = `
  varying vec3 vColor;
  void main() { float r = length(gl_PointCoord - .5) * 2.; if (r > 1.) discard;
    gl_FragColor = vec4(vColor, pow(1. - r, 1.5) * .55);
    #include <colorspace_fragment>
  }
`;
