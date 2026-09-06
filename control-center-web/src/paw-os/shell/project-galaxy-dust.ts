import * as THREE from 'three';

const vertexShader = `
  attribute vec4 aOrbit; attribute vec3 aColor; attribute vec2 aStar;
  uniform float uTime; uniform float uPixelScale; uniform float uSoft;
  varying vec3 vColor; varying float vOpacity;
  void main() {
    float r = aOrbit.x;
    float angle = aOrbit.y + uTime*(.0012+.009/(2.+r));
    float lift = aOrbit.z + sin(uTime*.035+aOrbit.w*6.283)*.06*uSoft;
    vec4 view = modelViewMatrix * vec4(cos(angle)*r,lift,sin(angle)*r,1.);
    gl_Position = projectionMatrix * view;
    float size = aStar.x * uPixelScale / max(1.,-view.z);
    gl_PointSize = clamp(size,1.,14.);
    vColor = aColor;
    // Preserve energy when a distant grain becomes smaller than one pixel.
    vOpacity = aStar.y * min(1.,size*size);
    vOpacity *= 1. + sin(uTime*.17+aOrbit.w*6.283)*.08*uSoft;
  }
`;
const fragmentShader = `
  varying vec3 vColor; varying float vOpacity; uniform float uSoft;
  void main() {
    vec2 p = gl_PointCoord*2.-1.; float r2 = dot(p,p); if (r2>1.) discard;
    float falloff = exp(-r2*mix(5.5,3.5,uSoft));
    gl_FragColor = vec4(vColor,falloff*vOpacity);
    #include <colorspace_fragment>
  }
`;

/** Two point-cloud draws: fine stellar dust and a faint, deeper luminous layer.
 * Both are decorative; task IDs and task lights remain owned by the stage. */
export function createGalaxyDust(seed: number) {
  let state = (seed ^ 0x5bd1e995) >>> 0;
  const random = () => { state = (Math.imul(state,1664525)+1013904223) >>> 0; return state/4294967296; };
  const group = new THREE.Group(); group.name = 'galaxy-stellar-dust';
  const materials: THREE.ShaderMaterial[] = [];
  const cool = ['#719bdb','#99c6e4','#cedfed','#5277b6','#94b9d1'].map((value) => new THREE.Color(value));
  const warm = ['#f6d495','#fff1ce','#dcac6b','#e7cfaa'].map((value) => new THREE.Color(value));
  const add = (count: number, soft: boolean) => {
    const orbits = new Float32Array(count*4), colors = new Float32Array(count*3), stars = new Float32Array(count*2);
    for (let i=0;i<count;i++) {
      const population = random(), choice = random(), arm = choice<.59 ? 0 : choice<.9 ? 1 : 2;
      const extent = [20.2,16.6,12.8][arm]!, phase = [0,2.48,4.62][arm]!;
      const core = population<.055, halo = population>.85;
      const r = core ? Math.pow(random(),.62)*3.6 : .18+Math.pow(random(),.65)*(halo ? 24 : extent);
      const scatter = (random()+random()+random()+random()-2)*(.38+.95/(r+1.));
      const angle = core || halo ? random()*Math.PI*2 : Math.log(r+.8)*2.7-4.1+phase+scatter;
      const thickness = soft ? 2.4 : core ? 1.15 : halo ? .8 : .34;
      const y = (random()+random()+random()-1.5)*thickness;
      orbits.set([r,angle,y,random()],i*4);
      const palette = random()<Math.exp(-r/5.8)*.82+(arm===1 ? .07 : 0) ? warm : cool;
      const color = palette[Math.floor(random()*palette.length)]!;
      const edge = halo ? .38 : Math.max(.18,Math.min(1,(extent+1-r)/3));
      const light = (.5+random()*.5)*edge;
      colors.set([color.r*light,color.g*light,color.b*light],i*3);
      const size = soft ? .1+random()*.29 : .018+Math.pow(random(),1.9)*.062;
      const opacity = soft ? .045+random()*.095 : .19+Math.pow(random(),2)*.38;
      stars.set([size,opacity],i*2);
    }
    const geometry = new THREE.BufferGeometry();
    // A position attribute establishes the draw count; orbit attributes carry
    // the animated position so no CPU upload is needed while the scene moves.
    geometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(count*3),3));
    geometry.setAttribute('aOrbit',new THREE.BufferAttribute(orbits,4));
    geometry.setAttribute('aColor',new THREE.BufferAttribute(colors,3));
    geometry.setAttribute('aStar',new THREE.BufferAttribute(stars,2));
    geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(),27);
    const material = new THREE.ShaderMaterial({vertexShader,fragmentShader,
      uniforms:{uTime:{value:0},uPixelScale:{value:1000},uSoft:{value:soft ? 1 : 0}},
      transparent:true,depthWrite:false,blending:THREE.AdditiveBlending});
    const points = new THREE.Points(geometry,material); points.renderOrder = soft ? -1 : -2;
    points.userData.galaxyDust = true;
    materials.push(material); group.add(points);
  };
  add(150_000,false); add(2_000,true);
  return {
    group,
    update(time: number) { for (const material of materials) material.uniforms.uTime!.value=time; },
    resize(pixelScale: number) { for (const material of materials) material.uniforms.uPixelScale!.value=pixelScale; },
  };
}
