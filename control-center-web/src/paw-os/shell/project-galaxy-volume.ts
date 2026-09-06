import * as THREE from 'three';

/** A bounded three-dimensional emission / extinction field. Dust absorbs the
 * light behind it; this is ray-marched through a volume, not a backdrop image. */
export function createGalaxyVolume(seed: number) {
  const bytes = new Uint8Array(64 ** 3);
  let state = seed || 1;
  for (let i = 0; i < bytes.length; i++) { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; bytes[i] = state >>> 24; }
  const noise = new THREE.Data3DTexture(bytes, 64, 64, 64);
  noise.format = THREE.RedFormat;
  noise.type = THREE.UnsignedByteType;
  noise.minFilter = noise.magFilter = THREE.LinearFilter;
  noise.wrapS = noise.wrapT = noise.wrapR = THREE.RepeatWrapping;
  noise.unpackAlignment = 1;
  noise.needsUpdate = true;
  const material = new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3, side: THREE.BackSide, transparent: true, depthWrite: false,
    uniforms: { uNoise: { value: noise }, uCamera: { value: new THREE.Vector3() }, uTime: { value: 0 }, uSteps: { value: 48 } },
    vertexShader: `out vec3 vPosition; void main(){vPosition=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
    fragmentShader: `
      precision highp sampler3D;
      in vec3 vPosition;
      uniform sampler3D uNoise;
      uniform vec3 uCamera;
      uniform float uTime;
      uniform float uSteps;
      out vec4 outColor;
      #define gl_FragColor outColor
      float field(vec3 p) {
        return texture(uNoise,p*.026+.5).r*.55+texture(uNoise,p*.081+.27).r*.3+texture(uNoise,p*.21+.73).r*.15;
      }
      void main(){
        vec3 direction=normalize(vPosition-uCamera);
        vec3 inverse=1./direction;
        vec3 lo=(-vec3(20.,3.,20.)-uCamera)*inverse;
        vec3 hi=( vec3(20.,3.,20.)-uCamera)*inverse;
        vec3 nearAxis=min(lo,hi),farAxis=max(lo,hi);
        float start=max(max(nearAxis.x,nearAxis.y),max(nearAxis.z,0.));
        float end=min(min(farAxis.x,farAxis.y),farAxis.z);
        if(end<=start)discard;
        float stepSize=(end-start)/uSteps;
        vec3 radiance=vec3(0.);
        float transmission=1.;
        for(int i=0;i<64;i++){
          if(float(i)>=uSteps||transmission<.015)break;
          vec3 p=uCamera+direction*(start+(float(i)+.5)*stepSize);
          float r=length(p.xz);
          float n=field(p);
          float falloff=(1.-smoothstep(12.,19.5,r))*exp(-r*.07);
          // The long-lived arm pattern is distinct from orbiting test stars.
          // Advecting it with each radius winds the arms into rings over time.
          float phase=atan(p.z,p.x)-1.65*log(r+.6)-uTime*.008+(n-.5)*.8;
          float arm=pow(.5+.5*cos(phase*2.),3.);
          float height=p.y+.65;
          float disk=exp(-height*height*3.5)*falloff;
          float stars=disk*(.045+arm*.4)*smoothstep(.22,.75,n);
          float bulge=exp(-r*r*.27-height*height*1.1)*.55;
          float lane=pow(.5+.5*cos((phase+.22)*2.),9.);
          float dust=disk*lane*smoothstep(.34,.66,n)*2.8;
          float density=stars+bulge+dust;
          float opacity=1.-exp(-density*stepSize);
          vec3 tint=mix(vec3(.64,.43,.27),vec3(.22,.32,.48),smoothstep(2.,14.,r));
          vec3 light=(tint*stars+vec3(.86,.69,.45)*bulge)*1.25/max(density,.0001);
          radiance+=transmission*opacity*light;
          transmission*=1.-opacity;
        }
        float alpha=1.-transmission;
        if(alpha<.002)discard;
        gl_FragColor=vec4(radiance/max(alpha,.001),alpha);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }
    `,
  });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(40, 6, 40), material);
  const cameraLocal = material.uniforms.uCamera!.value as THREE.Vector3;
  return {
    mesh,
    update(camera: THREE.Camera, seconds: number, quality: number) {
      camera.getWorldPosition(cameraLocal);
      mesh.worldToLocal(cameraLocal);
      material.uniforms.uTime!.value = seconds;
      material.uniforms.uSteps!.value = quality < .7 ? 32 : quality < .9 ? 40 : 48;
    },
    dispose() { noise.dispose(); },
  };
}
