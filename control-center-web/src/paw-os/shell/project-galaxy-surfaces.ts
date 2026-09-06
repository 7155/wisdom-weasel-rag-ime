import * as THREE from 'three';

const maps = [
  'paw-media/starfield/earth-1k.jpg',
  'paw-media/starfield/jupiter-1k.jpg',
  'paw-media/project-galaxy/moon-color-2k.jpg',
  'paw-media/starfield/saturn-1k.jpg',
  'paw-media/project-galaxy/mars-viking.jpg',
  'paw-media/starfield/mercury-1k.jpg',
] as const;
type TextureSlot = 'map' | 'bumpMap' | 'displacementMap' | 'alphaMap';

/** Stage-owned, local-only surface maps. A texture is loaded once per scene,
 * shared by its materials and released on close, including late arrivals. */
export class ProjectGalaxySurfaces {
  private readonly loader = new THREE.TextureLoader();
  private readonly ready = new Map<string, THREE.Texture>();
  private readonly waiting = new Map<string, Array<(texture: THREE.Texture) => void>>();
  private readonly failed = new Set<string>();
  private disposed = false;

  constructor(private readonly invalidate: () => void) {}

  private load(path: string, color: boolean, apply: (texture: THREE.Texture) => void) {
    if (this.disposed || this.failed.has(path)) return;
    const cached = this.ready.get(path);
    if (cached) { apply(cached); return; }
    const pending = this.waiting.get(path);
    if (pending) { pending.push(apply); return; }
    this.waiting.set(path, [apply]);
    this.loader.load(`${import.meta.env.BASE_URL}${path}`, (texture) => {
      if (this.disposed) { texture.dispose(); return; }
      texture.colorSpace = color ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.ClampToEdgeWrapping;
      texture.anisotropy = 2;
      this.ready.set(path, texture);
      const listeners = this.waiting.get(path) ?? [];
      this.waiting.delete(path);
      for (const listener of listeners) listener(texture);
      this.invalidate();
    }, undefined, () => { this.failed.add(path); this.waiting.delete(path); });
  }

  private bind(material: THREE.MeshStandardMaterial, path: string, slot: TextureSlot, color = false, onReady?: () => void) {
    let alive = true;
    material.addEventListener('dispose', () => { alive = false; });
    this.load(path, color, (texture) => {
      if (!alive) return;
      material[slot] = texture;
      material.needsUpdate = true;
      onReady?.();
    });
  }

  material(index: number) {
    const kind = index % maps.length;
    const material = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: kind === 0 ? .8 : 1, metalness: 0 });
    this.bind(material, maps[kind]!, 'map', true);
    if (kind === 2) {
      const height = 'paw-media/project-galaxy/moon-height-1k.jpg';
      this.bind(material, height, 'bumpMap');
      this.bind(material, height, 'displacementMap');
      material.bumpScale = .035;
      material.displacementScale = .012;
      material.displacementBias = -.006;
    }
    if (kind === 0) {
      // The blue ocean mask separates smooth water from rough land without
      // treating all surfaces as glossy plastic. The source map stays intact.
      material.onBeforeCompile = (shader) => {
        shader.fragmentShader = shader.fragmentShader.replace('#include <roughnessmap_fragment>', `
          #include <roughnessmap_fragment>
          float ocean = smoothstep(1.1, 1.8, diffuseColor.b / max(.015, diffuseColor.r));
          roughnessFactor = mix(.94, .36, ocean);
        `);
      };
      material.customProgramCacheKey = () => 'project-earth-ocean-v1';
    }
    return material;
  }

  clouds(geometry: THREE.BufferGeometry) {
    const material = new THREE.MeshStandardMaterial({ color: '#f2f5f7', roughness: 1, metalness: 0, transparent: true, opacity: .65, depthWrite: false });
    const cloud = new THREE.Mesh(geometry, material);
    cloud.scale.setScalar(1.012);
    cloud.visible = false;
    this.bind(material, 'paw-media/project-galaxy/earth-clouds-2k.jpg', 'alphaMap', false, () => { cloud.visible = true; });
    return cloud;
  }

  rings() {
    const material = new THREE.MeshStandardMaterial({ color: '#ddd4c2', roughness: 1, metalness: 0, transparent: true, opacity: .65, alphaTest: .12, depthWrite: false, side: THREE.DoubleSide });
    this.bind(material, 'paw-media/starfield/saturn-ring-1k.png', 'map', true);
    return material;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const texture of this.ready.values()) texture.dispose();
    this.ready.clear(); this.waiting.clear(); this.failed.clear();
  }
}
