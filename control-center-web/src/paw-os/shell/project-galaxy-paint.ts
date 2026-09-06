import * as THREE from 'three';
import { createGalaxyDust } from './project-galaxy-dust';

const noise = `
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f*f*(3.-2.*f);
    return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y);
  }
  float field(vec2 p) { return noise(p) * .57 + noise(p * 2.07 + 17.) * .28 + noise(p * 4.13 + 9.) * .15; }
`;
const brushVertex = `
  attribute vec4 aOrbit; attribute vec2 aBrush; attribute vec3 aColor;
  uniform float uTime; varying vec2 vUv; varying vec3 vColor; varying float vSeed;
  void main() {
    vUv = uv; vColor = aColor; vSeed = aOrbit.w;
    float along = position.x * aBrush.x, across = position.y * aBrush.y;
    float r = max(.08, aOrbit.x + along * .36 + across * .93);
    float a = aOrbit.y + (along * .93 - across * .36) / max(.6, aOrbit.x);
    a += uTime * (.0012 + .009 / (2. + aOrbit.x));
    gl_Position = projectionMatrix * modelViewMatrix * vec4(cos(a)*r, aOrbit.z, sin(a)*r, 1.);
  }
`;
const brushFragment = `
  varying vec2 vUv; varying vec3 vColor; varying float vSeed; uniform float uOpacity;
  void main() {
    float edge = .72 + .12 * sin(vUv.x * 13. + vSeed * 24.);
    float bristle = .5 + .5 * sin(vUv.y * 42. + sin(vUv.x * 9. + vSeed));
    float ends = pow(max(0.,sin(vUv.x * 3.14159)), .7);
    float alpha = (1.-smoothstep(edge-.14, edge, abs(vUv.y-.5)*2.)) * ends;
    alpha *= .72 + bristle * .28;
    if (alpha < .015) discard;
    float ridge = .86 + bristle * .2 + exp(-pow((vUv.y-.3)*12., 2.)) * .13;
    gl_FragColor = vec4(vColor * ridge, alpha * uOpacity);
    #include <colorspace_fragment>
  }
`;
const washFragment = `
  varying vec2 vUv; uniform float uTime;
  ${noise}
  float arm(float angle, float width) { float d = atan(sin(angle), cos(angle)); return exp(-pow(d/width, 2.)); }
  void main() {
    vec2 p = vec2(vUv.x-.5, .5-vUv.y) * 44.;
    float r = length(p), a = atan(p.y,p.x);
    float flow = log(r+.8)*2.7 - 4.1 + uTime*(.0012+.009/(2.+r));
    float n = field(p*.49 + vec2(uTime*.002, 0.));
    float warp = (n-.5)*.2;
    float width = .4 + .42/(r+1.);
    float first = arm(a-flow+warp, width)*(1.-smoothstep(14.,21.,r));
    float second = arm(a-flow-2.48+warp, width*.85)*(1.-smoothstep(10.,17.5,r))*.76;
    float third = arm(a-flow-4.62+warp, width*1.1)*(1.-smoothstep(7.,13.5,r))*.4;
    float arms = max(first, max(second, third));
    float dust = smoothstep(.2,.77,n);
    float striation = .9 + .1*sin((a-flow)*58. + n*16. + r*.9);
    float cloud = arms * (.48 + dust*.52) * striation;
    float veil = exp(-r*r/160.)*.025 * dust;
    float core = exp(-r*r/4.5) * (.68+field(p*1.3)*.32);
    float warmth = exp(-r/4.8);
    vec3 ultramarine = mix(vec3(.025,.06,.24), vec3(.13,.37,.57), dust);
    float litEdge = arm(a-flow+.21,width*.32) * (1.-smoothstep(5.,15.,r));
    vec3 pigment = mix(ultramarine, vec3(1.,.59,.21), min(.94,warmth*.85+litEdge*.36));
    vec3 color = pigment*cloud*.44 + vec3(.05,.08,.24)*veil + vec3(1.,.8,.45)*core*.3;
    float fade = 1.-smoothstep(19.,22.,r);
    gl_FragColor = vec4(color, fade);
    #include <colorspace_fragment>
  }
`;

/** Soft underpainting, a few flow strokes and two layers of fine stellar dust.
 * All detail is procedural. Five draw calls; frame updates only change time. */
export function createPaintedGalaxy(seed: number) {
  let randomState = seed || 1;
  const random = () => { randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0; return randomState / 4294967296; };
  const group = new THREE.Group(); group.name = 'painted-spiral-galaxy'; group.position.y = -.8;
  const materials: THREE.ShaderMaterial[] = [];
  const washMaterial = new THREE.ShaderMaterial({
    vertexShader: `varying vec2 vUv; void main() { vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
    fragmentShader: washFragment, uniforms: { uTime: { value: 0 } },
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  });
  const wash = new THREE.Mesh(new THREE.PlaneGeometry(44,44), washMaterial);
  wash.rotation.x = -Math.PI/2; wash.position.y = -.5; wash.renderOrder = -6;
  group.add(wash); materials.push(washMaterial);
  const blues = ['#25419b','#2867b7','#378dd2','#61b7d3','#a0d0d7','#d9e3dc'].map((color) => new THREE.Color(color));
  const golds = ['#c27c36','#e0a748','#f7cb7a','#fbe2ae','#fff3d6'].map((color) => new THREE.Color(color));
  const paint = (count: number, layer: 0 | 1) => {
    const plane = new THREE.PlaneGeometry(1,1,layer === 0 ? 18 : 6,1);
    const geometry = new THREE.InstancedBufferGeometry();
    geometry.index = plane.index; geometry.attributes.position = plane.attributes.position!; geometry.attributes.uv = plane.attributes.uv!;
    plane.dispose();
    const orbits = new Float32Array(count*4), brushes = new Float32Array(count*2), colors = new Float32Array(count*3);
    for (let i = 0; i < count; i++) {
      const choice = random(), arm = choice < .59 ? 0 : choice < .9 ? 1 : 2;
      const extent = [20.2,16.6,12.8][arm]!, phase = [0,2.48,4.62][arm]!;
      const r = .22 + Math.pow(random(),.72)*extent;
      const scatter = (random()+random()+random()-1.5)*(.21+.7/(r+1.));
      const angle = Math.log(r+.8)*2.7 - 4.1 + phase + scatter;
      const height = (random()+random()-1)*(.15+.3/(r+1.));
      orbits.set([r,angle,height,random()],i*4);
      const length = layer === 0 ? 2.4+random()*3.6 : .5+random()*2.1;
      const width = layer === 0 ? .22+random()*.48 : .085+random()*.18;
      brushes.set([length*(.35+r/22),width],i*2);
      const warmth = Math.exp(-r/4.8);
      const warm = random() < warmth*.85 + (arm === 1 ? .12 : .02);
      const palette = warm ? golds : blues;
      const color = palette[Math.min(palette.length-1,Math.floor(random()*palette.length))]!.clone();
      const edge = Math.max(.12,Math.min(1,(extent-r)/3));
      color.multiplyScalar((layer === 0 ? .78 : .82)*edge*(.65+random()*.35));
      colors.set(color.toArray(),i*3);
    }
    geometry.setAttribute('aOrbit',new THREE.InstancedBufferAttribute(orbits,4));
    geometry.setAttribute('aBrush',new THREE.InstancedBufferAttribute(brushes,2));
    geometry.setAttribute('aColor',new THREE.InstancedBufferAttribute(colors,3));
    geometry.instanceCount = count; geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(),23);
    const material = new THREE.ShaderMaterial({vertexShader:brushVertex,fragmentShader:brushFragment,
      uniforms:{uTime:{value:0},uOpacity:{value:layer === 0 ? .15 : .22}},
      transparent:true,depthWrite:false,side:THREE.DoubleSide,blending:THREE.NormalBlending});
    const mesh = new THREE.Mesh(geometry,material); mesh.renderOrder = -5+layer;
    materials.push(material); group.add(mesh);
  };
  paint(400,0); paint(1900,1);
  const dust = createGalaxyDust(seed); group.add(dust.group);
  return {
    group,
    update(time: number) { materials.forEach((material) => { material.uniforms.uTime!.value=time; }); dust.update(time); },
    resize(pixelScale: number) { dust.resize(pixelScale); },
  };
}
