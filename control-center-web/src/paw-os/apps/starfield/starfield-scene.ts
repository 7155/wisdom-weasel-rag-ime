/**
 * 星空 v2 WebGL stage — the immersive 3D renderer.
 *
 * A hand-driven three.js scene (no per-frame React): a procedurally textured
 * deep-sky dome with a milky-way band, particle star shells, nebulae, elliptical
 * orbit paths (q-jade/solar-system seasoning), planets with seeded surface +
 * normal maps, cloud shells, fresnel atmospheres, a granulated burning Sol,
 * handoff light beams and picked-body highlighting. All *work* motion comes
 * from `StarfieldMotion` profiles produced by the pure motion module, so the
 * 3D stage can never claim activity the Runtime does not report:
 * - orbit + spin advance by `motion.orbitRadPerS` / `spinRadPerS` (working);
 * - queue / review / failure appear as rings and light, never as motion;
 * - reduced motion stops the integrator and renders on demand only.
 *
 * Render budget: DPR capped by `starfieldPixelRatio` (hard ceiling + total
 * pixel budget) and stepped further down by a one-way quality ladder under
 * sustained slow frames, three shared unit-sphere geometries reused by every
 * body through THREE.LOD, all surface textures generated once and cached by
 * the texture factory, unchanged poll ticks skipped via
 * `sceneModelSignature`, zero per-frame allocations in the link updater, and
 * no rAF at all while the sky is hidden (`setRunning(false)` cancels it).
 *
 * DOM labels are positioned by projecting body anchors — and live handoff
 * beam midpoints — each frame, keeping the work text crisp and accessible
 * while the sky itself stays on the GPU. The backdrop is deliberately held
 * below them: dome tint, band and nebula opacity are tuned so the deep sky
 * reads as depth without ever competing with a task label or an orbit.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  METEOR_POOL_SIZE,
  METEOR_TRAIL_POINTS,
  METEOR_TRAIL_SPAN_S,
  meteorFade,
  meteorSpawn,
  nebulaBreath,
  twinkleOpacity,
  type MeteorSpawn,
} from './starfield-flourish';
import type { StarfieldTone } from './starfield-motion';
import {
  ellipticOrbitSamples,
  ellipticPosition,
  ellipticTrailSamples,
} from './starfield-orbit';
import { DeferredWorkQueue } from './starfield-deferred';
import {
  fallbackSurfaceTextureSize,
  ladderedPixelRatio,
  nextSlowFrameCount,
  PIXEL_RATIO_LADDER,
  SLOW_FRAMES_BEFORE_STEP,
  SPHERE_SEGMENTS,
  sphereLodLevels,
  starfieldAntialias,
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
  bodyRingSurfaceKey,
  bodySurfaceKey,
  centerSurfaceKey,
  StarfieldSurfaceLoader,
  type SurfaceKey,
} from './starfield-surface-catalog';
import {
  archetypeForPalette,
  archetypeForSeed,
  spectralStarColor,
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
/**
 * The backdrop is the room the work sits in, not the subject. Multiplying the
 * dome map down (and holding the particle layers at low opacity) keeps the
 * deep sky readable as depth while the DOM task labels, orbit ink and body
 * light stay the brightest things on screen. The PMREM environment is built
 * from the texture itself, so surface lighting keeps its full range.
 */
const SKY_DOME_TINT = 0x8b93ac;
/** Meteor shell: behind every orbit and star shell, in front of the dome. */
const METEOR_SHELL_RADIUS = 84;

const ARCHETYPE_ROUGHNESS: Record<PlanetArchetype, number> = {
  ocean: 0.62,
  rocky: 0.96,
  desert: 0.92,
  gas: 0.72,
  ice: 0.5,
  terra: 0.85,
};

/**
 * Base glow strength. A body carrying live work leads the sky; a settled,
 * stopped or unassigned one keeps its identity and orbit but stops competing
 * with the work — the same quieting the DOM label applies to its text.
 */
function bodyGlowOpacity(body: SceneBody): number {
  if (body.motion.working) return 0.62;
  if (body.idle) return body.kind === 'star' ? 0.3 : 0.18;
  return body.kind === 'star' ? 0.5 : 0.34;
}

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
  /** Working-body comet trail positions, updated along the ellipse. */
  trailPositions: THREE.BufferAttribute | null;
  /** Cloud shell that drifts slightly ahead of ground spin. */
  cloudSpin: THREE.Object3D | null;
  /** Scratch vector reused by the elliptical integrator (zero alloc). */
  orbitScratch: { x: number; y: number; z: number };
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
  /** Optional second corona sprite for a layered Sol bloom. */
  outerCorona: THREE.Sprite | null;
  cloudSpin: THREE.Object3D | null;
}

interface MeteorRuntime {
  line: THREE.Line;
  head: THREE.Sprite;
  lineMaterial: THREE.LineBasicMaterial;
  headMaterial: THREE.SpriteMaterial;
  positions: THREE.BufferAttribute;
  spawn: MeteorSpawn;
  /** Sky-time (elapsedS) when this streak ignites; negative age = waiting. */
  igniteAtS: number;
}

interface ShellTwinkle {
  material: THREE.PointsMaterial;
  baseOpacity: number;
  phase: number;
  speed: number;
}

interface NebulaBreathRuntime {
  sprite: THREE.Sprite;
  material: THREE.SpriteMaterial;
  baseScaleX: number;
  baseScaleY: number;
  baseOpacity: number;
  phase: number;
}

interface LinkRuntime {
  /** Real handoff identity — also keys the DOM beam label. */
  id: string;
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
  /** Beam midpoint in world space, refreshed by the link updater (no alloc). */
  midpoint: THREE.Vector3;
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
  private readonly labelAnchor = new THREE.Vector3();
  private readonly linkFrom = new THREE.Vector3();
  private readonly linkTo = new THREE.Vector3();

  private readonly textures = new StarfieldTextureFactory();
  private readonly surfaces = new StarfieldSurfaceLoader();
  private readonly deferred = new DeferredWorkQueue();
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
  private shellTwinkles: ShellTwinkle[] = [];
  private nebulaBreaths: NebulaBreathRuntime[] = [];
  private meteors: MeteorRuntime[] = [];
  private meteorRandom: () => number = () => 0.5;
  private bodies: BodyRuntime[] = [];
  private center: CenterRuntime | null = null;
  private links: LinkRuntime[] = [];
  private pickTargets: THREE.Object3D[] = [];
  private anchorById = new Map<string, THREE.Object3D>();
  private labelById = new Map<string, HTMLElement>();
  private linkLabelById = new Map<string, HTMLElement>();
  private backdropSeed = '';
  private modelSignature = '';

  private frameHandle = 0;
  private running = false;
  private reducedMotion = false;
  private dirty = true;
  private elapsedS = 0;
  private viewWidth = 1;
  private viewHeight = 1;
  /** One-way adaptive resolution ladder position (never steps back up). */
  private qualityStep = 0;
  private slowFrames = 0;
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
      antialias: starfieldAntialias(window.devicePixelRatio || 1),
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setClearColor(SPACE_CLEAR, 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.scene.fog = new THREE.FogExp2(SPACE_CLEAR, 0.011);

    this.textures.setAnisotropy(Math.min(4, this.renderer.capabilities.getMaxAnisotropy()));
    this.surfaces.setAnisotropy(Math.min(4, this.renderer.capabilities.getMaxAnisotropy()));
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
    if (reduced) this.hideMeteors();
    this.markDirty();
  }

  /** A frozen mid-flight streak is wrong under reduced motion: go dark. */
  private hideMeteors(): void {
    for (const meteor of this.meteors) {
      meteor.line.visible = false;
      meteor.head.visible = false;
      meteor.lineMaterial.opacity = 0;
      meteor.headMaterial.opacity = 0;
      meteor.igniteAtS = this.elapsedS + meteor.spawn.delayS;
    }
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
    this.applyViewport();
    if (!this.running) this.renderOnce();
  }

  private applyViewport(): void {
    this.renderer.setPixelRatio(ladderedPixelRatio(
      window.devicePixelRatio || 1,
      this.viewWidth,
      this.viewHeight,
      this.qualityStep,
    ));
    this.renderer.setSize(this.viewWidth, this.viewHeight, false);
    this.camera.aspect = this.viewWidth / this.viewHeight;
    this.camera.updateProjectionMatrix();
    this.markDirty();
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
    this.surfaces.dispose();
    this.deferred.cancelAll();
    this.renderer.dispose();
    this.shellTwinkles = [];
    this.nebulaBreaths = [];
    this.meteors = [];
    this.labelById.clear();
    this.linkLabelById.clear();
    // Exit must return the GPU immediately: dropping the context releases
    // its memory now instead of whenever the canvas is garbage collected.
    // The contextlost listener is already removed, so no fallback fires.
    try {
      this.renderer.forceContextLoss();
    } catch {
      // Context may already be lost — that is the state we want.
    }
  }

  /* ------------------------------------------------------- backdrop -- */

  private rebuildBackdrop(model: StarfieldSceneModel): void {
    this.disposeSubtree(this.backdropRoot);
    this.backdropRoot.clear();
    this.shellTwinkles = [];
    this.nebulaBreaths = [];
    this.meteors = [];
    const random = seededRandom(`${model.seed}:backdrop`);

    // Deep-sky dome: seeded nebulae, milky-way band and star scatter baked
    // into one equirect texture. Fog is disabled so the sky never washes out.
    if (!this.skyGeometry) {
      this.skyGeometry = new THREE.SphereGeometry(SKY_RADIUS, 48, 24);
      this.sharedGeometries.add(this.skyGeometry);
    }
    // The full dome costs >100ms of synchronous noise, which would stall the
    // very click that opens the sky. Show the cheap preview now and queue the
    // real one for the first idle moment.
    const skyMaterial = new THREE.MeshBasicMaterial({
      map: this.textures.skyPreview(model.seed),
      color: SKY_DOME_TINT,
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
    });
    const sky = new THREE.Mesh(this.skyGeometry, skyMaterial);
    sky.rotation.set(0.08 + random() * 0.22, random() * Math.PI * 2, 0);
    sky.renderOrder = -10;
    this.backdropRoot.add(sky);
    this.refreshEnvironment(skyMaterial.map!);
    const backdropSeed = model.seed;
    this.deferred.push(() => {
      if (this.disposed || this.backdropSeed !== backdropSeed) return;
      const full = this.textures.sky(backdropSeed);
      skyMaterial.map = full;
      skyMaterial.needsUpdate = true;
      this.refreshEnvironment(full);
      this.markDirty();
    });

    // Parallax star shells in front of the dome. They draw from the same
    // spectral population as the stars baked into the dome, so the near and
    // far layers cannot read as two different skies.
    const pickSpectral = () => spectralStarColor(random());
    const shells: Array<{ count: number; radius: [number, number]; size: number; opacity: number }> = [
      { count: 1100, radius: [64, 96], size: 0.5, opacity: 0.44 },
      { count: 520, radius: [44, 64], size: 0.78, opacity: 0.56 },
      { count: 240, radius: [28, 44], size: 1.12, opacity: 0.7 },
    ];
    for (const shell of shells) {
      const positions = new Float32Array(shell.count * 3);
      const colors = new Float32Array(shell.count * 3);
      for (let index = 0; index < shell.count; index += 1) {
        const radius = shell.radius[0] + random() * (shell.radius[1] - shell.radius[0]);
        const theta = random() * Math.PI * 2;
        const phi = Math.acos(2 * random() - 1);
        positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[index * 3 + 1] = radius * Math.cos(phi);
        positions[index * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta);
        const tint = pickSpectral();
        const brightness = 0.55 + random() * 0.45;
        colors[index * 3] = tint[0] * brightness;
        colors[index * 3 + 1] = tint[1] * brightness;
        colors[index * 3 + 2] = tint[2] * brightness;
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
      // Gentle whole-shell shimmer; each shell breathes on its own phase.
      this.shellTwinkles.push({
        material,
        baseOpacity: shell.opacity,
        phase: random() * Math.PI * 2,
        speed: 0.7 + random() * 0.6,
      });
    }

    // Dense milky-way particle band tilted against the ecliptic (q-jade).
    this.backdropRoot.add(this.buildMilkyWayBand(random));

    // Nebulae keep the sky from reading flat, but additive clouds behind a
    // white task label are exactly what makes text mushy — hold them low.
    const nebulaTints = [0x4c76ff, 0x9468eb, 0x54c4de, 0xff7a5c];
    nebulaTints.forEach((tint, index) => {
      const material = new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: tint,
        transparent: true,
        opacity: 0.15,
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
      this.nebulaBreaths.push({
        sprite,
        material,
        baseScaleX: sprite.scale.x,
        baseScaleY: sprite.scale.y,
        baseOpacity: material.opacity,
        phase: random() * Math.PI * 2,
      });
    });

    this.buildMeteorPool(model.seed);
    if (model.mode === 'galaxy') this.backdropRoot.add(this.buildSpiral(random));
  }

  /**
   * Galactic-plane particle band tilted vs the ecliptic — the same visual
   * idea as q-jade/solar-system's milky-way Points layer, scaled down to our
   * stage radius and driven by the scene seed. Deliberately thinner and
   * dimmer than the reference: a bright band sweeping behind the orbit chart
   * competes with the labels sitting on top of it.
   */
  private buildMilkyWayBand(random: () => number): THREE.Points {
    const count = 1300;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const tilt = 1.05; // ~60° like the reference
    const cosT = Math.cos(tilt);
    const sinT = Math.sin(tilt);
    for (let index = 0; index < count; index += 1) {
      const dist = 70 + random() * 55;
      const angle = random() * Math.PI * 2;
      const up = (random() - 0.5) * (6 + random() * 10);
      const flatX = dist * Math.cos(angle);
      const flatZ = dist * Math.sin(angle);
      positions[index * 3] = flatX * cosT;
      positions[index * 3 + 1] = flatX * sinT + up;
      positions[index * 3 + 2] = flatZ;
      const reddish = 0.45 + 0.55 * ((dist - 70) / 55);
      const br = 0.45 + random() * 0.55;
      colors[index * 3] = 1.0 * br;
      colors[index * 3 + 1] = (0.78 + 0.22 * (1 - reddish)) * br;
      colors[index * 3 + 2] = (0.55 + 0.45 * (1 - reddish)) * br;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({
      size: 0.4,
      map: this.dotTexture,
      transparent: true,
      opacity: 0.34,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
      fog: false,
    });
    const points = new THREE.Points(geometry, material);
    points.name = 'sf-milky-way';
    points.renderOrder = -8;
    return points;
  }

  /**
   * A small pool of shooting stars: pure presence, no Runtime meaning.
   * They only advance inside the motion integrator, so reduced motion
   * (system preference or the OS-level data-reduce-motion switch) stops
   * spawning entirely and `setReducedMotion` hides any streak mid-flight.
   */
  private buildMeteorPool(seed: string): void {
    this.meteorRandom = seededRandom(`${seed}:meteor`);
    for (let index = 0; index < METEOR_POOL_SIZE; index += 1) {
      const positions = new THREE.BufferAttribute(new Float32Array(METEOR_TRAIL_POINTS * 3), 3);
      const colors = new Float32Array(METEOR_TRAIL_POINTS * 3);
      for (let point = 0; point < METEOR_TRAIL_POINTS; point += 1) {
        // Head white-blue, tail fading to nothing — the taper lives in the
        // vertex colors so per-frame work is position + opacity only.
        const fade = (1 - point / (METEOR_TRAIL_POINTS - 1)) ** 1.6;
        colors[point * 3] = 0.86 * fade;
        colors[point * 3 + 1] = 0.92 * fade;
        colors[point * 3 + 2] = fade;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', positions);
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
      const lineMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        fog: false,
      });
      const line = new THREE.Line(geometry, lineMaterial);
      line.visible = false;
      line.frustumCulled = false;
      this.backdropRoot.add(line);
      const headMaterial = new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: 0xeaf3ff,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        fog: false,
      });
      const head = new THREE.Sprite(headMaterial);
      head.visible = false;
      this.backdropRoot.add(head);
      const spawn = meteorSpawn(this.meteorRandom, METEOR_SHELL_RADIUS);
      this.meteors.push({
        line,
        head,
        lineMaterial,
        headMaterial,
        positions,
        spawn,
        // Stagger first appearances so the pool never volleys at once.
        igniteAtS: this.elapsedS + spawn.delayS + index * 2.4,
      });
    }
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

  /**
   * Swap a body's procedural surface for its real photographic map once the
   * async load completes (q-jade/solar-system craft: texture with graceful
   * color fallback — here the fallback *is* the procedural surface, so the
   * sky is never blank while the photo is in flight).
   *
   * The swap goes through the deferred queue rather than running inside the
   * load callback: a Room with eight named planets finishes eight fetches at
   * roughly the same moment, and uploading eight 1k maps plus recompiling
   * eight materials in one frame is exactly the hitch this whole path exists
   * to avoid. The stale-signature guard drops deliveries that raced a scene
   * rebuild; the shared cache makes the rebuilt scene's re-request a
   * synchronous hit.
   */
  private applySurfaceMap(
    key: SurfaceKey,
    material: THREE.MeshStandardMaterial | THREE.MeshBasicMaterial,
    tint?: THREE.Color,
  ): void {
    const signature = this.modelSignature;
    this.surfaces.load(key, (texture) => {
      if (this.disposed || signature !== this.modelSignature) return;
      this.deferred.push(() => {
        if (this.disposed || signature !== this.modelSignature) return;
        material.map = texture;
        // Photo maps bake their own relief; the procedural normal map would
        // fight it with mismatched detail.
        if ('normalMap' in material) material.normalMap = null;
        material.color.set(tint ?? 0xffffff);
        material.needsUpdate = true;
        this.markDirty();
      });
    });
  }

  /**
   * Attach the real ring strip once it loads. Nothing is built up front: a
   * planet whose ring map never arrives simply keeps its bare disc, and the
   * mesh joins the body's tilt group so teardown disposes it with everything
   * else. UVs are remapped so u runs across the band and v around the ring,
   * which keeps each ringlet a perfect circle instead of smearing the strip
   * across a planar projection.
   */
  private attachStripRing(parent: THREE.Object3D, size: number, key: SurfaceKey): void {
    const signature = this.modelSignature;
    this.surfaces.load(key, (texture) => {
      if (this.disposed || signature !== this.modelSignature || !parent.parent) return;
      this.deferred.push(() => this.buildStripRing(parent, size, texture, signature));
    });
  }

  private buildStripRing(
    parent: THREE.Object3D,
    size: number,
    texture: THREE.Texture,
    signature: string,
  ): void {
    if (this.disposed || signature !== this.modelSignature || !parent.parent) return;
    const innerR = size * 1.24;
    const outerR = size * 2.3;
    const geometry = new THREE.RingGeometry(innerR, outerR, 96, 1);
    geometry.rotateX(-Math.PI / 2);
    const positions = geometry.attributes.position as THREE.BufferAttribute;
    const uv = geometry.attributes.uv as THREE.BufferAttribute;
    for (let index = 0; index < positions.count; index += 1) {
      const x = positions.getX(index);
      const z = positions.getZ(index);
      const radius = Math.hypot(x, z);
      uv.setXY(
        index,
        (radius - innerR) / (outerR - innerR),
        (Math.atan2(z, x) + Math.PI) / (Math.PI * 2),
      );
    }
    uv.needsUpdate = true;
    const ring = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      map: texture,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      depthWrite: false,
    }));
    ring.rotation.x = 0.3;
    ring.rotation.z = 0.16;
    ring.renderOrder = 2;
    parent.add(ring);
    this.markDirty();
  }

  private buildCenter(model: StarfieldSceneModel): CenterRuntime {
    const center = model.center!;
    const group = new THREE.Group();
    const toneColor = TONE_COLORS[center.motion.tone];
    const surfaceKey = centerSurfaceKey(model.mode, center);
    let outerCorona: THREE.Sprite | null = null;
    let cloudSpin: THREE.Object3D | null = null;

    let mesh: THREE.Mesh;
    if (center.kind === 'sun') {
      const sunMaterial = new THREE.MeshBasicMaterial({ map: this.textures.sun(model.seed) });
      if (surfaceKey) this.applySurfaceMap(surfaceKey, sunMaterial);
      mesh = new THREE.Mesh(this.sphereGeometries.high, sunMaterial);
      mesh.scale.setScalar(center.size);
      const chromosphere = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(0xffa14f, 0.72),
      );
      chromosphere.scale.setScalar(center.size * 1.28);
      group.add(chromosphere);
      const light = new THREE.PointLight(0xffc37a, 150, 0, 2);
      group.add(light);
      // Sol still leads the Room, but its bloom is the one thing bright
      // enough to swallow a task label that drifts across it.
      const corona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: 0xffc46a,
        transparent: true,
        opacity: 0.76,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      corona.scale.setScalar(center.size * 5.4);
      group.add(corona);
      outerCorona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glowTexture,
        color: 0xff8a3a,
        transparent: true,
        opacity: 0.3,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      outerCorona.scale.setScalar(center.size * 9.2);
      group.add(outerCorona);
    } else {
      const archetype = archetypeForSeed(model.seed);
      const { width } = surfaceKey
        ? fallbackSurfaceTextureSize(center.size)
        : surfaceTextureSize(center.size);
      const maps = this.textures.planet({
        seed: model.seed,
        archetype,
        baseColor: 0x6fa4ec,
        width,
      });
      const centerMaterial = new THREE.MeshStandardMaterial({
        map: maps.map,
        normalMap: maps.normalMap,
        roughness: ARCHETYPE_ROUGHNESS[archetype],
        metalness: 0.04,
      });
      if (surfaceKey) this.applySurfaceMap(surfaceKey, centerMaterial);
      mesh = new THREE.Mesh(this.sphereGeometries.high, centerMaterial);
      mesh.scale.setScalar(center.size);
      const atmosphere = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(toneColor, 0.55),
      );
      atmosphere.scale.setScalar(center.size * 1.18);
      group.add(atmosphere);
      if (archetype === 'terra' || archetype === 'ocean') {
        cloudSpin = this.buildCloudShell(model.seed, center.size, width);
        group.add(cloudSpin);
      }
      const ringGeo = this.buildRadialRingGeometry(center.size * 1.5, center.size * 2.25, 96);
      const saturnRing = new THREE.Mesh(
        ringGeo,
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
      opacity: center.kind === 'sun' ? 0.55 : 0.42,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    const glowBaseScale = center.size * (center.kind === 'sun' ? 7.4 : 3.6);
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
      outerCorona,
      cloudSpin,
    };
  }

  /** Cloud shell slightly larger than the body — drifts ahead of ground spin. */
  private buildCloudShell(seed: string, size: number, width: number): THREE.Mesh {
    const material = new THREE.MeshBasicMaterial({
      map: this.textures.cloud(seed, Math.max(64, width)),
      transparent: true,
      depthWrite: false,
      opacity: 0.85,
      blending: THREE.NormalBlending,
    });
    const mesh = new THREE.Mesh(this.sphereGeometries.medium, material);
    mesh.scale.setScalar(size * 1.035);
    mesh.renderOrder = 2;
    return mesh;
  }

  /**
   * RingGeometry with radial UVs so the procedural ring alpha map reads as
   * concentric bands (same UV remap as q-jade Saturn rings).
   */
  private buildRadialRingGeometry(inner: number, outer: number, segments: number): THREE.RingGeometry {
    const geometry = new THREE.RingGeometry(inner, outer, segments, 1);
    const pos = geometry.attributes.position;
    const uv = geometry.attributes.uv;
    if (pos && uv) {
      for (let index = 0; index < pos.count; index += 1) {
        const x = pos.getX(index);
        const y = pos.getY(index);
        const radius = Math.sqrt(x * x + y * y);
        const t = (radius - inner) / Math.max(outer - inner, 1e-6);
        uv.setXY(index, t, 0.5);
      }
      uv.needsUpdate = true;
    }
    return geometry;
  }

  private buildBody(model: StarfieldSceneModel, body: SceneBody, drawnRings: Set<string>): void {
    const orbitGroup = new THREE.Group();
    orbitGroup.rotation.z = body.inclinationRad;
    // Carrier kept for hierarchy stability; elliptical motion writes the
    // focus-centered cartesian position onto `anchor` each frame.
    const carrier = new THREE.Group();
    const anchor = new THREE.Group();
    const scratch = { x: 0, y: 0, z: 0 };
    ellipticPosition(body.orbitRadius, body.eccentricity, body.phaseRad, scratch);
    anchor.position.set(scratch.x, scratch.y, scratch.z);
    carrier.add(anchor);
    orbitGroup.add(carrier);
    this.modelRoot.add(orbitGroup);

    const toneColor = TONE_COLORS[body.motion.tone];
    const surface = BODY_PALETTE[body.paletteIndex % BODY_PALETTE.length]!;
    const archetype = body.kind === 'star' ? null : archetypeForPalette(body.paletteIndex);

    // Axial tilt wraps the spinning surface (q-jade tiltGroup).
    const tiltGroup = new THREE.Group();
    tiltGroup.rotation.z = body.axialTiltRad;
    anchor.add(tiltGroup);

    const surfaceKey = bodySurfaceKey(model.mode, body);

    // One material shared by every LOD level; textures cached by identity.
    let material: THREE.Material;
    if (body.kind === 'star') {
      material = new THREE.MeshBasicMaterial({
        map: this.textures.star(),
        color: new THREE.Color(surface).lerp(new THREE.Color(0xffffff), 0.4),
      });
    } else {
      const { width } = surfaceKey
        ? fallbackSurfaceTextureSize(body.size)
        : surfaceTextureSize(body.size);
      const maps = this.textures.planet({
        seed: body.id,
        archetype: archetype!,
        baseColor: surface,
        width,
      });
      const bodyMaterial = new THREE.MeshStandardMaterial({
        map: maps.map,
        normalMap: maps.normalMap,
        roughness: ARCHETYPE_ROUGHNESS[archetype!],
        metalness: 0.04,
      });
      if (surfaceKey) this.applySurfaceMap(surfaceKey, bodyMaterial);
      material = bodyMaterial;
    }
    const lod = new THREE.LOD();
    for (const level of sphereLodLevels(body.size)) {
      const levelMesh = new THREE.Mesh(this.sphereGeometries[level.detail], material);
      levelMesh.scale.setScalar(body.size);
      levelMesh.userData.sfBodyId = body.id;
      lod.addLevel(levelMesh, level.distance);
    }
    lod.userData.sfBodyId = body.id;
    tiltGroup.add(lod);

    // A photographic surface already carries its own weather, so only Earth
    // keeps the procedural cloud shell — drifting clouds over Mars or Jupiter
    // would fight the real map and cost a second transparent sphere.
    const cloudsWelcome = surfaceKey === null || surfaceKey === 'earth';
    let cloudSpin: THREE.Object3D | null = null;
    if (cloudsWelcome && (archetype === 'terra' || archetype === 'ocean')) {
      const { width } = surfaceTextureSize(body.size);
      cloudSpin = this.buildCloudShell(body.id, body.size, width);
      tiltGroup.add(cloudSpin);
    }

    // Only the Room planet actually named Saturn earns the real ring strip;
    // it is attached when (and if) the alpha map arrives.
    const ringKey = bodyRingSurfaceKey(model.mode, body);
    if (ringKey) this.attachStripRing(tiltGroup, body.size, ringKey);

    // Fresnel atmosphere only for bodies large enough to read it; moons rely
    // on the tone glow, which halves their draw calls.
    if (body.kind !== 'star' && body.size >= 0.45) {
      const shell = new THREE.Mesh(
        this.sphereGeometries.medium,
        this.atmosphereMaterial(toneColor, body.idle ? 0.2 : 0.5),
      );
      shell.scale.setScalar(body.size * 1.22);
      anchor.add(shell);
    }

    const glow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glowTexture,
      color: toneColor,
      transparent: true,
      opacity: bodyGlowOpacity(body),
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    const glowBaseScale = body.size * (body.kind === 'star' ? 6 : 4.4);
    glow.scale.setScalar(glowBaseScale);
    anchor.add(glow);

    // Elliptical orbit path, deduplicated by a/e/inclination.
    if (body.orbitRadius > 0.05 && model.mode !== 'galaxy') {
      const ringKey = `${body.orbitRadius.toFixed(2)}:${body.eccentricity.toFixed(3)}:${body.inclinationRad.toFixed(3)}`;
      if (!drawnRings.has(ringKey)) {
        drawnRings.add(ringKey);
        orbitGroup.add(this.buildOrbitPath(body.orbitRadius, body.eccentricity, body.motion.working));
      }
    }

    let trailPositions: THREE.BufferAttribute | null = null;
    if (body.motion.working) {
      const trail = this.buildTrail(body.orbitRadius, body.eccentricity, body.phaseRad, toneColor);
      trailPositions = trail.geometry.getAttribute('position') as THREE.BufferAttribute;
      orbitGroup.add(trail);
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
      trailPositions,
      cloudSpin,
      orbitScratch: scratch,
    });
  }

  /**
   * Orbit guide in the reference's single soft ink (q-jade/solar-system uses
   * 0x8cb8ce at low opacity for every path): one consistent quiet line per
   * orbit that only brightens under a working body, so the paths read as a
   * calm chart instead of a tangle of competing colors.
   */
  private buildOrbitPath(semiMajor: number, eccentricity: number, working: boolean): THREE.LineLoop {
    const positions = ellipticOrbitSamples(semiMajor, eccentricity, 160);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return new THREE.LineLoop(geometry, new THREE.LineBasicMaterial({
      color: 0x8cb8ce,
      transparent: true,
      opacity: working ? 0.4 : 0.16,
    }));
  }

  /** A comet tail behind a working body, riding its elliptical path. */
  private buildTrail(
    semiMajor: number,
    eccentricity: number,
    trueAnomalyRad: number,
    toneColor: number,
  ): THREE.Line {
    const segments = 42;
    const positions = ellipticTrailSamples(semiMajor, eccentricity, trueAnomalyRad, 0.95, segments);
    const colors = new Float32Array(segments * 3);
    const tone = new THREE.Color(toneColor);
    for (let index = 0; index < segments; index += 1) {
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
      id: link.id,
      line,
      packet,
      fromId: link.fromId,
      toId: link.toId,
      live: link.live,
      positions,
      lineDistances,
      packetSeed: seededRandom(link.id)(),
      dashShift: 0,
      midpoint: new THREE.Vector3(),
    });
  }

  /* ------------------------------------------------------ labelling -- */

  private collectLabels(): void {
    this.labelById.clear();
    this.linkLabelById.clear();
    for (const element of this.labelLayer.querySelectorAll<HTMLElement>('[data-sf-body]')) {
      const id = element.dataset.sfBody;
      if (id) this.labelById.set(id, element);
    }
    for (const element of this.labelLayer.querySelectorAll<HTMLElement>('[data-sf-link]')) {
      const id = element.dataset.sfLink;
      if (id) this.linkLabelById.set(id, element);
    }
  }

  private updateLabels(): void {
    const project = (label: HTMLElement | undefined, world: THREE.Vector3) => {
      if (!label) return;
      this.worldPosition.copy(world).project(this.camera);
      if (this.worldPosition.z > 1 || this.worldPosition.z < -1) {
        label.style.opacity = '0';
        return;
      }
      const x = (this.worldPosition.x * 0.5 + 0.5) * this.viewWidth;
      const y = (-this.worldPosition.y * 0.5 + 0.5) * this.viewHeight;
      label.style.opacity = '';
      label.style.transform = `translate(-50%, 0) translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    };
    const place = (id: string, target: THREE.Object3D, offsetY: number) => {
      const label = this.labelById.get(id);
      if (!label) return;
      target.getWorldPosition(this.labelAnchor);
      this.labelAnchor.y -= offsetY;
      project(label, this.labelAnchor);
    };
    if (this.center) place('center', this.center.group, this.center.size * 1.6);
    for (const runtime of this.bodies) place(runtime.body.id, runtime.anchor, runtime.body.size * 1.7);
    // Live handoffs name the work that is moving, right on the beam.
    if (this.linkLabelById.size) {
      for (const link of this.links) project(this.linkLabelById.get(link.id), link.midpoint);
    }
  }

  /* ----------------------------------------------------- frame loop -- */

  private readonly markDirty = (): void => {
    this.dirty = true;
  };

  private readonly frame = (): void => {
    if (this.disposed || !this.running) return;
    this.frameHandle = requestAnimationFrame(this.frame);

    const dt = Math.min(this.clock.getDelta(), MAX_FRAME_DT);
    this.trackFrameBudget(dt);
    const motionDt = this.reducedMotion ? 0 : dt;
    this.elapsedS += motionDt;

    let animated = false;
    if (motionDt > 0) {
      for (const runtime of this.bodies) {
        const { motion } = runtime.body;
        if (motion.orbitRadPerS > 0) {
          runtime.angleRad += motion.orbitRadPerS * runtime.body.speedFactor * motionDt;
          ellipticPosition(
            runtime.body.orbitRadius,
            runtime.body.eccentricity,
            runtime.angleRad,
            runtime.orbitScratch,
          );
          runtime.anchor.position.set(
            runtime.orbitScratch.x,
            runtime.orbitScratch.y,
            runtime.orbitScratch.z,
          );
          if (runtime.trailPositions) {
            ellipticTrailSamples(
              runtime.body.orbitRadius,
              runtime.body.eccentricity,
              runtime.angleRad,
              0.95,
              runtime.trailPositions.count,
              runtime.trailPositions.array as Float32Array,
            );
            runtime.trailPositions.needsUpdate = true;
          }
          animated = true;
        }
        if (motion.spinRadPerS > 0) {
          runtime.spinTarget.rotation.y += motion.spinRadPerS * motionDt;
          if (runtime.cloudSpin) {
            runtime.cloudSpin.rotation.y += motion.spinRadPerS * motionDt * 1.18;
          }
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
          if (this.center.cloudSpin) {
            this.center.cloudSpin.rotation.y += this.center.spinRadPerS * motionDt * 1.15;
          }
          animated = true;
        }
        if (this.center.pulseHz > 0) {
          const wave = Math.sin(this.elapsedS * this.center.pulseHz * Math.PI * 2);
          this.center.glow.scale.setScalar(this.center.glowBaseScale * (1 + wave * 0.12));
          if (this.center.outerCorona) {
            const pulse = 1 + wave * 0.18;
            this.center.outerCorona.scale.setScalar(this.center.size * 9.2 * pulse);
            (this.center.outerCorona.material as THREE.SpriteMaterial).opacity =
              0.22 + (wave * 0.5 + 0.5) * 0.16;
          }
          animated = true;
        }
      }
      // Ambient backdrop drift: decoration, never a work signal.
      this.backdropRoot.rotation.y += dt * 0.004;
      const spiral = this.backdropRoot.getObjectByName('sf-spiral');
      if (spiral) spiral.rotation.y += dt * 0.01;
      this.updateFlourishes();
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

  /**
   * Adaptive resolution: count sustained slow frames (ignoring clamped
   * outliers such as tab switches) and step the quality ladder down so the
   * sky yields GPU headroom back to the OS instead of dragging the pointer.
   */
  private trackFrameBudget(dt: number): void {
    if (dt >= MAX_FRAME_DT) return;
    this.slowFrames = nextSlowFrameCount(this.slowFrames, dt);
    if (this.slowFrames >= SLOW_FRAMES_BEFORE_STEP && this.qualityStep < PIXEL_RATIO_LADDER.length - 1) {
      this.qualityStep += 1;
      this.slowFrames = 0;
      this.applyViewport();
    }
  }

  /**
   * Advance the decorative presence layer — twinkle, nebula breathing and
   * meteor streaks. Runs only inside the motion integrator (motionDt > 0),
   * so reduced motion stills all of it; zero allocations per frame.
   */
  private updateFlourishes(): void {
    for (const twinkle of this.shellTwinkles) {
      twinkle.material.opacity = twinkleOpacity(
        twinkle.baseOpacity,
        this.elapsedS * twinkle.speed,
        twinkle.phase,
      );
    }
    for (const breath of this.nebulaBreaths) {
      const factor = nebulaBreath(this.elapsedS, breath.phase);
      breath.sprite.scale.set(breath.baseScaleX * factor, breath.baseScaleY * factor, 1);
      breath.material.opacity = breath.baseOpacity * (0.88 + (factor - 1) * 3);
    }
    for (const meteor of this.meteors) {
      const age = this.elapsedS - meteor.igniteAtS;
      if (age < 0) continue;
      if (age >= meteor.spawn.lifeS) {
        meteor.line.visible = false;
        meteor.head.visible = false;
        meteor.spawn = meteorSpawn(this.meteorRandom, METEOR_SHELL_RADIUS);
        meteor.igniteAtS = this.elapsedS + meteor.spawn.delayS;
        continue;
      }
      const { origin, velocity, lifeS, headScale } = meteor.spawn;
      const brightness = meteorFade(age, lifeS);
      const step = METEOR_TRAIL_SPAN_S / (METEOR_TRAIL_POINTS - 1);
      for (let point = 0; point < METEOR_TRAIL_POINTS; point += 1) {
        const at = Math.max(age - point * step, 0);
        meteor.positions.setXYZ(
          point,
          origin[0] + velocity[0] * at,
          origin[1] + velocity[1] * at,
          origin[2] + velocity[2] * at,
        );
      }
      meteor.positions.needsUpdate = true;
      meteor.lineMaterial.opacity = brightness * 0.9;
      meteor.headMaterial.opacity = brightness;
      meteor.head.position.set(
        origin[0] + velocity[0] * age,
        origin[1] + velocity[1] * age,
        origin[2] + velocity[2] * age,
      );
      meteor.head.scale.setScalar(headScale * (1.1 + brightness * 0.9));
      meteor.line.visible = true;
      meteor.head.visible = true;
    }
  }

  private renderOnce(): void {
    this.controls.update();
    // Beam midpoints come from the link updater; a resize outside the loop
    // must refresh them or its labels would snap back to the origin.
    this.updateLinks(0);
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
      link.midpoint.copy(from).lerp(to, 0.5);
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
      material.opacity = selected ? 0.95 : bodyGlowOpacity(runtime.body);
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
    // Factory- and surface-loader-owned textures outlive scene rebuilds and
    // are disposed exactly once by their owner on stage teardown.
    if (textured.map && !this.textures.owns(textured.map) && !this.surfaces.owns(textured.map)) {
      textured.map.dispose();
    }
    if (textured.normalMap && !this.textures.owns(textured.normalMap)) textured.normalMap.dispose();
    material.dispose();
  }
}
