/**
 * 星空 v2 WebGL stage — the immersive 3D renderer.
 *
 * A hand-driven three.js scene (no per-frame React): a procedurally textured
 * deep-sky dome with a milky-way band, particle star shells, nebulae, orbit
 * rings, planets with seeded surface + normal maps and fresnel atmospheres,
 * a granulated burning Sol, handoff light beams and picked-body highlighting.
 * All *work* motion comes from `StarfieldMotion` profiles produced by the
 * pure motion module, so the 3D stage can never claim activity the Runtime
 * does not report:
 * - orbit + spin advance by `motion.orbitRadPerS` / `spinRadPerS` (working);
 * - queue / review / failure appear as rings and light, never as motion;
 * - reduced motion stops the integrator and renders on demand only.
 *
 * Render budget: DPR capped by `starfieldPixelRatio` (hard ceiling + total
 * pixel budget), three shared unit-sphere geometries reused by every body
 * through THREE.LOD, all surface textures generated once and cached by the
 * texture factory, unchanged poll ticks skipped via `sceneModelSignature`,
 * zero per-frame allocations in the link updater, and no rAF at all while
 * the sky is hidden (`setRunning(false)` cancels the loop).
 *
 * DOM labels are positioned by projecting body anchors each frame, keeping
 * text crisp and accessible while the sky itself stays on the GPU.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { StarfieldTone } from './starfield-motion';
import {
  SPHERE_SEGMENTS,
  sphereLodLevels,
  starfieldPixelRatio,
  surfaceTextureSize,
  type SphereDetail,
} from './starfield-render-quality';
import {
  SCENE_STAGE_RADIUS,
  sceneModelSignature,
  type SceneBody,
  type StarfieldSceneModel,
} from './starfield-scene-model';
import {
  archetypeForPalette,
  archetypeForSeed,
  StarfieldTextureFactory,
  type PlanetArchetype,
} from './starfield-textures';

const TONE_COLORS: Record<StarfieldTone, number> = {
  working: 0x5b9bf0,
  queued: 0x8794ad,
  waiting: 0xd9b25c,
  review: 0xf0b25c,
  done: 0x4fc180,
  attention: 0xee7a6d,
  paused: 0x7d8496,
  muted: 0x66738f,
};

const BODY_PALETTE = [0x5b9bf0, 0xde8273, 0xdcb25e, 0x9a7ae0, 0x55c3dd, 0x8fd0a0];
const SPACE_CLEAR = 0x05070f;
const MAX_FRAME_DT = 0.1;
/** Deep-sky dome radius: outside every orbit, inside the camera far plane. */
const SKY_RADIUS = 170;

const ARCHETYPE_ROUGHNESS: Record<PlanetArchetype, number> = {
  ocean: 0.62,
  rocky: 0.96,
  desert: 0.92,
  gas: 0.72,
  ice: 0.5,
  terra: 0.85,
};

/** Deterministic LCG stream seeded by a string, mirrors starfieldHash. */
function seededRandom(seed: string): () => number {
  let state = 0x811c9dc5;
  for (let index = 0; index < seed.length; index += 1) {
    state ^= seed.charCodeAt(index);
    state = Math.imul(state, 0x01000193);
  }
  state >>>= 0;
  if (state === 0) state = 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

/* ------------------------------------------------------------------ */
/* Runtime bookkeeping                                                 */
/* ------------------------------------------------------------------ */

interface BodyRuntime {
  body: SceneBody;
  carrier: THREE.Group;
  anchor: THREE.Group;
  /** Rotated for self-spin: the LOD holding every detail level. */
  spinTarget: THREE.Object3D;
  glow: THREE.Sprite;
  glowBaseScale: number;
  statusRingMaterial: THREE.Material | null;
  angleRad: number;
  pulseSeed: number;
}

interface CenterRuntime {
  mesh: THREE.Mesh;
  group: THREE.Group;
  glow: THREE.Sprite;
  glowBaseScale: number;
  /** World radius — shared unit geometry means we must not read params. */
  size: number;
  spinRadPerS: number;
  pulseHz: number;
}

interface LinkRuntime {
  line: THREE.Line;
  packet: THREE.Sprite | null;
  fromId: string;
  toId: string;
  live: boolean;
  positions: THREE.BufferAttribute;
  /** Persistent two-entry attribute; never reallocated per frame. */
  lineDistances: THREE.BufferAttribute;
  packetSeed: number;
  /** Accumulated dash-pattern shift for the flowing live-handoff look. */
  dashShift: number;
}

export interface StarfieldStageOptions {
  canvas: HTMLCanvasElement;
  labelLayer: HTMLElement;
  onPick?: (bodyId: string | null) => void;
  onContextLost?: () => void;
}

/* ------------------------------------------------------------------ */
/* The stage                                                           */
/* ------------------------------------------------------------------ */

export class StarfieldStage {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly canvas: HTMLCanvasElement;
  private readonly labelLayer: HTMLElement;
  private readonly onPick: ((bodyId: string | null) => void) | undefined;
  private readonly contextLostCallback: (() => void) | undefined;
  private readonly clock = new THREE.Clock();
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly worldPosition = new THREE.Vector3();
  private readonly linkFrom = new THREE.Vector3();
  private readonly linkTo = new THREE.Vector3();

  private readonly textures = new StarfieldTextureFactory();
  private readonly pmrem: THREE.PMREMGenerator;
  private envTarget: THREE.WebGLRenderTarget | null = null;
  private readonly glowTexture: THREE.Texture;
  private readonly dotTexture: THREE.Texture;
  private readonly sphereGeometries: Record<SphereDetail, THREE.SphereGeometry>;
  private skyGeometry: THREE.SphereGeometry | null = null;
  private readonly sharedGeometries = new Set<THREE.BufferGeometry>();
  private readonly atmosphereMaterials = new Map<string, THREE.ShaderMaterial>();
  private readonly cachedMaterials = new Set<THREE.Material>();

  private modelRoot = new THREE.Group();
  private backdropRoot = new THREE.Group();
  private bodies: BodyRuntime[] = [];
  private center: CenterRuntime | null = null;
  private links: LinkRuntime[] = [];
  private pickTargets: THREE.Object3D[] = [];
  private anchorById = new Map<string, THREE.Object3D>();
  private labelById = new Map<string, HTMLElement>();
  private backdropSeed = '';
  private modelSignature = '';

  private frameHandle = 0;
  private running = false;
  private reducedMotion = false;
  private dirty = true;
  private elapsedS = 0;
  private viewWidth = 1;
  private viewHeight = 1;
  private pointerMoved = false;
  private hoveredId: string | null = null;
  private pointerDownAt: { x: number; y: number; timeMs: number } | null = null;
  private selectedId: string | null = null;
  private disposed = false;

  constructor(options: StarfieldStageOptions) {
    this.canvas = options.canvas;
    this.labelLayer = options.labelLayer;
    this.onPick = options.onPick;
    this.contextLostCallback = options.onContextLost;
    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setClearColor(SPACE_CLEAR, 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.scene.fog = new THREE.FogExp2(SPACE_CLEAR, 0.011);

    this.textures.setAnisotropy(Math.min(4, this.renderer.capabilities.getMaxAnisotropy()));
    this.pmrem = new THREE.PMREMGenerator(this.renderer);
    this.glowTexture = this.textures.glow();
    this.dotTexture = this.textures.dot();
    this.sphereGeometries = {
      high: new THREE.SphereGeometry(1, SPHERE_SEGMENTS.high[0], SPHERE_SEGMENTS.high[1]),
      medium: new THREE.SphereGeometry(1, SPHERE_SEGMENTS.medium[0], SPHERE_SEGMENTS.medium[1]),
      low: new THREE.SphereGeometry(1, SPHERE_SEGMENTS.low[0], SPHERE_SEGMENTS.low[1]),
    };
    for (const geometry of Object.values(this.sphereGeometries)) this.sharedGeometries.add(geometry);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 400);
    this.camera.position.set(0, SCENE_STAGE_RADIUS * 0.78, SCENE_STAGE_RADIUS * 1.72);

    this.controls = new OrbitControls(this.camera, options.canvas);
    this.controls.enablePan = false;
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.minDistance = SCENE_STAGE_RADIUS * 0.7;
    this.controls.maxDistance = SCENE_STAGE_RADIUS * 4;
    this.controls.minPolarAngle = Math.PI * 0.12;
    this.controls.maxPolarAngle = Math.PI * 0.55;
    this.controls.autoRotateSpeed = 0.22;
    this.controls.addEventListener('change', this.markDirty);

    this.scene.add(new THREE.AmbientLight(0x2c3a5c, 0.55));
    this.scene.add(new THREE.HemisphereLight(0x9db8e8, 0x141020, 0.5));
    const key = new THREE.DirectionalLight(0xdfe8ff, 1.7);
    key.position.set(7, 11, 5);
    this.scene.add(key);
    this.scene.add(this.backdropRoot);
    this.scene.add(this.modelRoot);

    this.canvas.addEventListener('pointerdown', this.handlePointerDown);
    this.canvas.addEventListener('pointerup', this.handlePointerUp);
    this.canvas.addEventListener('pointermove', this.handlePointerMove);
    this.canvas.addEventListener('pointerleave', this.handlePointerLeave);
    this.canvas.addEventListener('webglcontextlost', this.handleContextLost);
  }

  /* ------------------------------------------------- public control -- */

  setModel(model: StarfieldSceneModel): void {
    if (this.disposed) return;
    if (model.seed !== this.backdropSeed) {
      this.backdropSeed = model.seed;
      this.rebuildBackdrop(model);
    }
    // Poll ticks usually return an unchanged sky — skip the full geometry
    // teardown/upload and keep every accumulated orbit/spin angle.
    const signature = sceneModelSignature(model);
    if (signature !== this.modelSignature) {
      this.modelSignature = signature;
      this.rebuildModel(model);
    }
    this.collectLabels();
    this.markDirty();
  }

  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
    this.controls.autoRotate = !reduced;
    this.markDirty();
  }

  setSelected(bodyId: string | null): void {
    this.selectedId = bodyId;
    this.applySelectionHighlight();
    this.markDirty();
  }

  setRunning(running: boolean): void {
    if (this.disposed || this.running === running) return;
    this.running = running;
    if (running) {
      this.clock.getDelta();
      this.markDirty();
      this.frameHandle = requestAnimationFrame(this.frame);
    } else {
      cancelAnimationFrame(this.frameHandle);
    }
  }

  resize(width: number, height: number): void {
    if (this.disposed || width < 2 || height < 2) return;
    this.viewWidth = width;
    this.viewHeight = height;
    this.renderer.setPixelRatio(starfieldPixelRatio(window.devicePixelRatio || 1, width, height));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.markDirty();
    if (!this.running) this.renderOnce();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.frameHandle);
    this.canvas.removeEventListener('pointerdown', this.handlePointerDown);
    this.canvas.removeEventListener('pointerup', this.handlePointerUp);
    this.canvas.removeEventListener('pointermove', this.handlePointerMove);
    this.canvas.removeEventListener('pointerleave', this.handlePointerLeave);
    this.canvas.removeEventListener('webglcontextlost', this.handleContextLost);
    this.controls.removeEventListener('change', this.markDirty);
    this.controls.dispose();
    this.disposeSubtree(this.scene);
    for (const geometry of this.sharedGeometries) geometry.dispose();
    this.sharedGeometries.clear();
    for (const material of this.atmosphereMaterials.values()) material.dispose();
    this.atmosphereMaterials.clear();
    this.cachedMaterials.clear();
    this.scene.environment = null;
    this.envTarget?.dispose();
    this.pmrem.dispose();
    this.textures.dispose();
    this.renderer.dispose();
  }

  /* ------------------------------------------------------- backdrop -- */

  private rebuildBackdrop(model: StarfieldSceneModel): void {
    this.disposeSubtree(this.backdropRoot);
    this.backdropRoot.clear();
    const random = seededRandom(`${model.seed}:backdrop`);

    // Deep-sky dome: seeded nebulae, milky-way band and star scatter baked
    // into one equirect texture. Fog is disabled so the sky never washes out.
    if (!this.skyGeometry) {
      this.skyGeometry = new THREE.SphereGeometry(SKY_RADIUS, 48, 24);
      this.sharedGeometries.add(this.skyGeometry);
    }
    const skyTexture = this.textures.sky(model.seed);
    const sky = new THREE.Mesh(this.skyGeometry, new THREE.MeshBasicMaterial({
      map: skyTexture,
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
    }));
    sky.rotation.set(0.08 + random() * 0.22, random() * Math.PI * 2, 0);
    sky.renderOrder = -10;
    this.backdropRoot.add(sky);
    this.refreshEnvironment(skyTexture);

    // Parallax star shells in front of the dome. The dome carries density,
    // so the shells stay lean.
    const shells: Array<{ count: number; radius: [number, number]; size: number; opacity: number }> = [
      { count: 900, radius: [64, 96], size: 0.55, opacity: 0.6 },
      { count: 420, radius: [44, 64], size: 0.8, opacity: 0.75 },
      { count: 200, radius: [28, 44], size: 1.15, opacity: 0.95 },
    ];
    for (const shell of shells) {
      const positions = new Float32Array(shell.count * 3);
      const colors = new Float32Array(shell.count * 3);
      const tint = new THREE.Color();
      for (let index = 0; index < shell.count; index += 1) {
        const radius = shell.radius[0] + random() * (shell.radius[1] - shell.radius[0]);
        const theta = random() * Math.PI * 2;
        const phi = Math.acos(2 * random() - 1);
        positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[index * 3 + 1] = radius * Math.cos(phi);
        positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
        tint.setHSL(0.55 + random() * 0.16, 0.35 + random() * 0.3, 0.62 + random() * 0.3);
        colors[index * 3] = tint.r;
        colors[index * 3 + 1] = tint.g;
        colors[index * 3 + 2] = tint.b;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const material = new THREE.PointsMaterial({
        size: shell.size,
        map: this.dotTexture,
        transparent: true,
        opacity: shell.opacity,
        vertexColors: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      });
      this.backdropRoot.add(new THREE.Points(geometry, material));
    }

    const nebulaTints = [0x4c76ff, 0x9468eb, 0x54c4de];
    nebulaTints.forEach((tint, index) => {
      const material = new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: tint,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const sprite = new THREE.Sprite(material);
      const angle = random() * Math.PI * 2;
      const distance = 30 + random() * 26;
      sprite.position.set(
        Math.cos(angle) * distance,
        -6 + random() * 16,
        Math.sin(angle) * distance - 8,
      );
      const scale = 46 + random() * 30 + index * 6;
      sprite.scale.set(scale, scale * (0.6 + random() * 0.3), 1);
      this.backdropRoot.add(sprite);
    });

    if (model.mode === 'galaxy') this.backdropRoot.add(this.buildSpiral(random));
  }

  /** Image-based lighting from the sky dome so surfaces never look plastic. */
  private refreshEnvironment(skyTexture: THREE.Texture): void {
    try {
      const target = this.pmrem.fromEquirectangular(skyTexture);
      this.envTarget?.dispose();
      this.envTarget = target;
      this.scene.environment = target.texture;
      this.scene.environmentIntensity = 0.42;
    } catch {
      this.scene.environment = null;
    }
  }

  private buildSpiral(random: () => number): THREE.Points {
    const count = 1500;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const tint = new THREE.Color();
    for (let index = 0; index < count; index += 1) {
      const arm = index % 2;
      const t = random();
      const radius = 1.5 + t * SCENE_STAGE_RADIUS * 1.5;
      const angle = arm * Math.PI + t * 4.4 + (random() - 0.5) * 0.55;
      positions[index * 3] = Math.cos(angle) * radius;
      positions[index * 3 + 1] = (random() - 0.5) * 0.9;
      positions[index * 3 + 2] = Math.sin(angle) * radius;
      tint.setHSL(0.58 + random() * 0.12, 0.5, 0.55 + random() * 0.3);
      colors[index * 3] = tint.r;
      colors[index * 3 + 1] = tint.g;
      colors[index * 3 + 2] = tint.b;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({
      size: 0.5,
      map: this.dotTexture,
      transparent: true,
      opacity: 0.5,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(geometry, material);
    points.name = 'sf-spiral';
    return points;
  }

  /* ---------------------------------------------------- scene build -- */

  private rebuildModel(model: StarfieldSceneModel): void {
    this.disposeSubtree(this.modelRoot);
    this.modelRoot.clear();
    this.bodies = [];
    this.links = [];
    this.pickTargets = [];
    this.anchorById.clear();

    this.center = model.center ? this.buildCenter(model) : null;
    const drawnRings = new Set<string>();
    for (const body of model.bodies) this.buildBody(model, body, drawnRings);
    for (const runtime of this.bodies) this.anchorById.set(runtime.body.id, runtime.anchor);
    if (this.center) this.anchorById.set('center', this.center.group);
    for (const link of model.links) this.buildLink(link);
    this.applySelectionHighlight();
  }

  /** Fresnel rim shell shared per tone color — light, never a work signal. */
  private atmosphereMaterial(color: number, intensity: number): THREE.ShaderMaterial {
    const key = `${color}:${intensity}`;
    const cached = this.atmosphereMaterials.get(key);
    if (cached) return cached;
    const material = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.FrontSide,
      uniforms: {
        uColor: { value: new THREE.Color(color) },
        uIntensity: { value: intensity },
      },
      vertexShader: `
        varying float vRim;
        void main() {
          vec3 n = normalize(normalMatrix * normal);
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vec3 viewDir = normalize(-mv.xyz);
          vRim = pow(1.0 - clamp(dot(n, viewDir), 0.0, 1.0), 2.6);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform vec3 uColor;
        uniform float uIntensity;
        varying float vRim;
        void main() {
          gl_FragColor = vec4(uColor, vRim * uIntensity);
        }`,
    });
    this.atmosphereMaterials.set(key, material);
    this.cachedMaterials.add(material);
    return material;
  }

  private buildCenter(model: StarfieldSceneModel): CenterRuntime {
    const center = model.center!;
    const group = new THREE.Group();
    const toneColor = TONE_COLORS[center.motion.tone];

    let mesh: THREE.Mesh;
    if (center.kind === 'sun') {
      mesh = new THREE.Mesh(
        this.sphereGeometries.high,
        new THREE.MeshBasicMaterial({ map: this.textures.sun(model.seed) }),
      );
      mesh.scale.setScalar(center.size);
      const chromosphere = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(0xffa14f, 0.6),
      );
      chromosphere.scale.setScalar(center.size * 1.26);
      group.add(chromosphere);
      const light = new THREE.PointLight(0xffc37a, 130, 0, 2);
      group.add(light);
      const corona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: 0xffc46a,
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      corona.scale.setScalar(center.size * 5.4);
      group.add(corona);
    } else {
      const archetype = archetypeForSeed(model.seed);
      const { width } = surfaceTextureSize(center.size);
      const maps = this.textures.planet({
        seed: model.seed,
        archetype,
        baseColor: 0x6fa4ec,
        width,
      });
      mesh = new THREE.Mesh(
        this.sphereGeometries.high,
        new THREE.MeshStandardMaterial({
          map: maps.map,
          normalMap: maps.normalMap,
          roughness: ARCHETYPE_ROUGHNESS[archetype],
          metalness: 0.04,
        }),
      );
      mesh.scale.setScalar(center.size);
      const atmosphere = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(toneColor, 0.55),
      );
      atmosphere.scale.setScalar(center.size * 1.18);
      group.add(atmosphere);
      const saturnRing = new THREE.Mesh(
        new THREE.RingGeometry(center.size * 1.5, center.size * 2.25, 96),
        new THREE.MeshBasicMaterial({
          map: this.textures.ring(model.seed),
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      saturnRing.rotation.x = -Math.PI / 2 + 0.34;
      saturnRing.rotation.z = 0.22;
      group.add(saturnRing);
    }
    mesh.userData.sfBodyId = 'center';
    group.add(mesh);

    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glowTexture,
      color: toneColor,
      transparent: true,
      opacity: center.kind === 'sun' ? 0.5 : 0.42,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    const glowBaseScale = center.size * (center.kind === 'sun' ? 7 : 3.6);
    glow.scale.setScalar(glowBaseScale);
    group.add(glow);

    this.modelRoot.add(group);
    this.pickTargets.push(mesh);
    return {
      mesh,
      group,
      glow,
      glowBaseScale,
      size: center.size,
      spinRadPerS: center.motion.spinRadPerS,
      pulseHz: center.motion.pulseHz,
    };
  }

  private buildBody(model: StarfieldSceneModel, body: SceneBody, drawnRings: Set<string>): void {
    const orbitGroup = new THREE.Group();
    orbitGroup.rotation.z = body.inclinationRad;
    const carrier = new THREE.Group();
    carrier.rotation.y = body.phaseRad;
    const anchor = new THREE.Group();
    anchor.position.set(body.orbitRadius, 0, 0);
    carrier.add(anchor);
    orbitGroup.add(carrier);
    this.modelRoot.add(orbitGroup);

    const toneColor = TONE_COLORS[body.motion.tone];
    const surface = BODY_PALETTE[body.paletteIndex % BODY_PALETTE.length]!;

    // One material shared by every LOD level; textures cached by identity.
    let material: THREE.Material;
    if (body.kind === 'star') {
      material = new THREE.MeshBasicMaterial({
        map: this.textures.star(),
        color: new THREE.Color(surface).lerp(new THREE.Color(0xffffff), 0.4),
      });
    } else {
      const archetype = archetypeForPalette(body.paletteIndex);
      const { width } = surfaceTextureSize(body.size);
      const maps = this.textures.planet({
        seed: body.id,
        archetype,
        baseColor: surface,
        width,
      });
      material = new THREE.MeshStandardMaterial({
        map: maps.map,
        normalMap: maps.normalMap,
        roughness: ARCHETYPE_ROUGHNESS[archetype],
        metalness: 0.04,
      });
    }
    const lod = new THREE.LOD();
    for (const level of sphereLodLevels(body.size)) {
      const levelMesh = new THREE.Mesh(this.sphereGeometries[level.detail], material);
      levelMesh.scale.setScalar(body.size);
      levelMesh.userData.sfBodyId = body.id;
      lod.addLevel(levelMesh, level.distance);
    }
    lod.userData.sfBodyId = body.id;
    anchor.add(lod);

    // Fresnel atmosphere only for bodies large enough to read it; moons rely
    // on the tone glow, which halves their draw calls.
    if (body.kind !== 'star' && body.size >= 0.45) {
      const shell = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(toneColor, body.motion.tone === 'muted' ? 0.22 : 0.5),
      );
      shell.scale.setScalar(body.size * 1.22);
      anchor.add(shell);
    }

    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glowTexture,
      color: toneColor,
      transparent: true,
      opacity: body.motion.working ? 0.62 : body.kind === 'star' ? 0.5 : 0.3,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    const glowBaseScale = body.size * (body.kind === 'star' ? 6 : 4.4);
    glow.scale.setScalar(glowBaseScale);
    anchor.add(glow);

    // Orbit path, deduplicated by radius + inclination.
    if (body.orbitRadius > 0.05 && model.mode !== 'galaxy') {
      const ringKey = `${body.orbitRadius.toFixed(2)}:${body.inclinationRad.toFixed(3)}`;
      if (!drawnRings.has(ringKey)) {
        drawnRings.add(ringKey);
        orbitGroup.add(this.buildOrbitPath(body.orbitRadius, body.motion.working));
      }
    }

    if (body.motion.working) {
      carrier.add(this.buildTrail(body.orbitRadius, toneColor));
    }

    const { statusRing, statusRingMaterial } = this.buildStatusRing(body, toneColor);
    if (statusRing) anchor.add(statusRing);

    this.pickTargets.push(lod);
    this.bodies.push({
      body,
      carrier,
      anchor,
      spinTarget: lod,
      glow,
      glowBaseScale,
      statusRingMaterial,
      angleRad: body.phaseRad,
      pulseSeed: body.phaseRad * 7.13,
    });
  }

  private buildOrbitPath(radius: number, working: boolean): THREE.LineLoop {
    const segments = 128;
    const positions = new Float32Array(segments * 3);
    for (let index = 0; index < segments; index += 1) {
      const angle = (index / segments) * Math.PI * 2;
      positions[index * 3] = Math.cos(angle) * radius;
      positions[index * 3 + 1] = 0;
      positions[index * 3 + 2] = Math.sin(angle) * radius;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return new THREE.LineLoop(geometry, new THREE.LineBasicMaterial({
      color: working ? 0x93b0e2 : 0x4a5878,
      transparent: true,
      opacity: working ? 0.4 : 0.22,
    }));
  }

  /** A comet tail behind a working body, riding inside its carrier group. */
  private buildTrail(radius: number, toneColor: number): THREE.Line {
    const segments = 42;
    const span = 0.95;
    const positions = new Float32Array(segments * 3);
    const colors = new Float32Array(segments * 3);
    const tone = new THREE.Color(toneColor);
    for (let index = 0; index < segments; index += 1) {
      const delta = (index / (segments - 1)) * span;
      positions[index * 3] = Math.cos(delta) * radius;
      positions[index * 3 + 1] = 0;
      positions[index * 3 + 2] = Math.sin(delta) * radius;
      const fade = 1 - index / (segments - 1);
      colors[index * 3] = tone.r * fade;
      colors[index * 3 + 1] = tone.g * fade;
      colors[index * 3 + 2] = tone.b * fade;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return new THREE.Line(geometry, new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }));
  }

  private buildStatusRing(
    body: SceneBody,
    toneColor: number,
  ): { statusRing: THREE.Object3D | null; statusRingMaterial: THREE.Material | null } {
    if (body.motion.ring === 'none') return { statusRing: null, statusRingMaterial: null };
    if (body.motion.ring === 'queued') {
      const segments = 64;
      const radius = body.size * 2.1;
      const positions = new Float32Array(segments * 3);
      for (let index = 0; index < segments; index += 1) {
        const angle = (index / segments) * Math.PI * 2;
        positions[index * 3] = Math.cos(angle) * radius;
        positions[index * 3 + 1] = 0;
        positions[index * 3 + 2] = Math.sin(angle) * radius;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      const material = new THREE.LineDashedMaterial({
        color: toneColor,
        transparent: true,
        opacity: 0.85,
        dashSize: radius * 0.24,
        gapSize: radius * 0.18,
      });
      const ring = new THREE.LineLoop(geometry, material);
      ring.computeLineDistances();
      return { statusRing: ring, statusRingMaterial: material };
    }
    const material = new THREE.MeshBasicMaterial({
      color: toneColor,
      transparent: true,
      opacity: body.motion.ring === 'attention' ? 0.8 : 0.65,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(body.size * 1.8, body.size * (body.motion.ring === 'attention' ? 2.15 : 2.0), 48),
      material,
    );
    ring.rotation.x = -Math.PI / 2;
    return { statusRing: ring, statusRingMaterial: material };
  }

  private buildLink(link: { id: string; fromId: string; toId: string; live: boolean; failed: boolean }): void {
    const positions = new THREE.BufferAttribute(new Float32Array(6), 3);
    const lineDistances = new THREE.BufferAttribute(new Float32Array(2), 1);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', positions);
    geometry.setAttribute('lineDistance', lineDistances);
    const color = link.failed ? TONE_COLORS.attention : link.live ? 0x55c3dd : TONE_COLORS.done;
    const material = link.live || link.failed
      ? new THREE.LineDashedMaterial({
          color,
          transparent: true,
          opacity: link.live ? 0.9 : 0.55,
          dashSize: 0.5,
          gapSize: 0.35,
        })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.32 });
    const line = new THREE.Line(geometry, material);
    this.modelRoot.add(line);

    let packet: THREE.Sprite | null = null;
    if (link.live) {
      packet = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: 0xd9f6ff,
        transparent: true,
        opacity: 0.95,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      packet.scale.setScalar(0.62);
      this.modelRoot.add(packet);
    }
    this.links.push({
      line,
      packet,
      fromId: link.fromId,
      toId: link.toId,
      live: link.live,
      positions,
      lineDistances,
      packetSeed: seededRandom(link.id)(),
      dashShift: 0,
    });
  }

  /* ------------------------------------------------------ labelling -- */

  private collectLabels(): void {
    this.labelById.clear();
    for (const element of this.labelLayer.querySelectorAll<HTMLElement>('[data-sf-body]')) {
      const id = element.dataset.sfBody;
      if (id) this.labelById.set(id, element);
    }
  }

  private updateLabels(): void {
    const place = (id: string, target: THREE.Object3D, offsetY: number) => {
      const label = this.labelById.get(id);
      if (!label) return;
      target.getWorldPosition(this.worldPosition);
      this.worldPosition.y -= offsetY;
      this.worldPosition.project(this.camera);
      if (this.worldPosition.z > 1 || this.worldPosition.z < -1) {
        label.style.opacity = '0';
        return;
      }
      const x = (this.worldPosition.x * 0.5 + 0.5) * this.viewWidth;
      const y = (-this.worldPosition.y * 0.5 + 0.5) * this.viewHeight;
      label.style.opacity = '';
      label.style.transform = `translate(-50%, 0) translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    };
    if (this.center) place('center', this.center.group, this.center.size * 1.6);
    for (const runtime of this.bodies) place(runtime.body.id, runtime.anchor, runtime.body.size * 1.7);
  }

  /* ----------------------------------------------------- frame loop -- */

  private readonly markDirty = (): void => {
    this.dirty = true;
  };

  private readonly frame = (): void => {
    if (this.disposed || !this.running) return;
    this.frameHandle = requestAnimationFrame(this.frame);

    const dt = Math.min(this.clock.getDelta(), MAX_FRAME_DT);
    const motionDt = this.reducedMotion ? 0 : dt;
    this.elapsedS += motionDt;

    let animated = false;
    if (motionDt > 0) {
      for (const runtime of this.bodies) {
        const { motion } = runtime.body;
        if (motion.orbitRadPerS > 0) {
          runtime.angleRad += motion.orbitRadPerS * runtime.body.speedFactor * motionDt;
          runtime.carrier.rotation.y = runtime.angleRad;
          animated = true;
        }
        if (motion.spinRadPerS > 0) {
          runtime.spinTarget.rotation.y += motion.spinRadPerS * motionDt;
          animated = true;
        }
        if (motion.pulseHz > 0) {
          const wave = Math.sin(this.elapsedS * motion.pulseHz * Math.PI * 2 + runtime.pulseSeed);
          runtime.glow.scale.setScalar(runtime.glowBaseScale * (1 + wave * 0.16));
          if (runtime.statusRingMaterial && 'opacity' in runtime.statusRingMaterial) {
            (runtime.statusRingMaterial as THREE.Material & { opacity: number }).opacity = 0.55 + (wave * 0.5 + 0.5) * 0.4;
          }
          animated = true;
        }
      }
      if (this.center) {
        if (this.center.spinRadPerS > 0) {
          this.center.mesh.rotation.y += this.center.spinRadPerS * motionDt;
          animated = true;
        }
        if (this.center.pulseHz > 0) {
          const wave = Math.sin(this.elapsedS * this.center.pulseHz * Math.PI * 2);
          this.center.glow.scale.setScalar(this.center.glowBaseScale * (1 + wave * 0.1));
          animated = true;
        }
      }
      // Ambient backdrop drift: decoration, never a work signal.
      this.backdropRoot.rotation.y += dt * 0.004;
      const spiral = this.backdropRoot.getObjectByName('sf-spiral');
      if (spiral) spiral.rotation.y += dt * 0.01;
      animated = true;
    }

    if (this.updateLinks(motionDt)) animated = true;
    const controlsMoved = this.controls.update();
    this.updateHover();

    if (animated || controlsMoved || this.dirty) {
      this.dirty = false;
      this.updateLabels();
      this.renderer.render(this.scene, this.camera);
    }
  };

  private renderOnce(): void {
    this.controls.update();
    this.updateLabels();
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
  }

  private updateLinks(motionDt: number): boolean {
    if (!this.links.length) return false;
    const from = this.linkFrom;
    const to = this.linkTo;
    let animated = false;
    for (const link of this.links) {
      const fromObject = this.anchorById.get(link.fromId) ?? this.center?.group;
      const toObject = this.anchorById.get(link.toId);
      if (!fromObject || !toObject) continue;
      fromObject.getWorldPosition(from);
      toObject.getWorldPosition(to);
      link.positions.setXYZ(0, from.x, from.y, from.z);
      link.positions.setXYZ(1, to.x, to.y, to.z);
      link.positions.needsUpdate = true;
      const material = link.line.material as THREE.LineDashedMaterial | THREE.LineBasicMaterial;
      if ('dashSize' in material) {
        // Two-point dashed line: shift the lineDistance attribute so the
        // dash pattern visibly flows from source to target while live.
        if (link.live && motionDt > 0) {
          link.dashShift = (link.dashShift + motionDt * 1.6) % (material.dashSize + material.gapSize);
          animated = true;
        }
        const length = from.distanceTo(to);
        link.lineDistances.setX(0, -link.dashShift);
        link.lineDistances.setX(1, length - link.dashShift);
        link.lineDistances.needsUpdate = true;
      }
      if (link.packet) {
        const t = (this.elapsedS * 0.32 + link.packetSeed) % 1;
        link.packet.position.lerpVectors(from, to, t);
        if (motionDt > 0) animated = true;
      }
    }
    return animated;
  }

  /* -------------------------------------------------------- picking -- */

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.pointerDownAt = { x: event.clientX, y: event.clientY, timeMs: performance.now() };
  };

  private readonly handlePointerUp = (event: PointerEvent): void => {
    const start = this.pointerDownAt;
    this.pointerDownAt = null;
    if (!start || !this.onPick) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (moved > 7 || performance.now() - start.timeMs > 600) return;
    this.onPick(this.pickAt(event));
  };

  private readonly handlePointerMove = (event: PointerEvent): void => {
    const bounds = this.canvas.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    this.pointerMoved = true;
  };

  private readonly handlePointerLeave = (): void => {
    this.hoveredId = null;
    this.canvas.style.cursor = '';
  };

  private readonly handleContextLost = (): void => {
    this.setRunning(false);
    this.contextLostCallback?.();
  };

  private pickAt(event: PointerEvent): string | null {
    const bounds = this.canvas.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    return this.raycastPointer();
  }

  private raycastPointer(): string | null {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    // LOD targets delegate to their currently visible level mesh.
    const hit = this.raycaster.intersectObjects(this.pickTargets, false)[0];
    return hit ? String(hit.object.userData.sfBodyId ?? '') || null : null;
  }

  private updateHover(): void {
    if (!this.pointerMoved) return;
    this.pointerMoved = false;
    const id = this.raycastPointer();
    if (id === this.hoveredId) return;
    this.hoveredId = id;
    this.canvas.style.cursor = id ? 'pointer' : '';
    this.markDirty();
  }

  private applySelectionHighlight(): void {
    for (const runtime of this.bodies) {
      const selected = runtime.body.id === this.selectedId;
      const material = runtime.glow.material;
      material.opacity = selected ? 0.95 : runtime.body.motion.working ? 0.62 : runtime.body.kind === 'star' ? 0.5 : 0.3;
      runtime.glow.scale.setScalar(selected ? runtime.glowBaseScale * 1.25 : runtime.glowBaseScale);
    }
    if (this.center) {
      this.center.glow.material.opacity = this.selectedId === 'center' ? 0.72 : 0.45;
    }
  }

  /* -------------------------------------------------------- cleanup -- */

  private disposeSubtree(root: THREE.Object3D): void {
    root.traverse((object) => {
      const mesh = object as Partial<THREE.Mesh> & Partial<THREE.Points> & Partial<THREE.Sprite>;
      if (mesh.geometry && !this.sharedGeometries.has(mesh.geometry)) mesh.geometry.dispose();
      const material = mesh.material;
      if (Array.isArray(material)) {
        for (const item of material) this.disposeMaterial(item);
      } else if (material) {
        this.disposeMaterial(material);
      }
    });
  }

  private disposeMaterial(material: THREE.Material): void {
    // Cached fresnel materials outlive rebuilds; the stage disposes them once.
    if (this.cachedMaterials.has(material)) return;
    const textured = material as THREE.Material & {
      map?: THREE.Texture | null;
      normalMap?: THREE.Texture | null;
    };
    if (textured.map && !this.textures.owns(textured.map)) textured.map.dispose();
    if (textured.normalMap && !this.textures.owns(textured.normalMap)) textured.normalMap.dispose();
    material.dispose();
  }
}
