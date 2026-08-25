/**
 * 星空 v2 WebGL stage — the immersive 3D renderer.
 *
 * A hand-driven three.js scene (no per-frame React): a spectral-type star
 * sphere with a milky-way band (craft ported from the MIT q-jade/solar-system
 * reference), nebulae, readable orbit lines, planets carrying real downscaled
 * NASA-style maps (async, procedural color until ready), a textured burning
 * Sol, handoff light beams and picked-body highlighting. All *work* motion
 * comes from `StarfieldMotion` profiles produced by the pure motion module,
 * so the 3D stage can never claim activity the Runtime does not report:
 * - orbit + spin advance by `motion.orbitRadPerS` / `spinRadPerS` (working);
 * - queue / review / failure appear as rings and light, never as motion;
 * - reduced motion stops the integrator and renders on demand only.
 *
 * Performance contract (hard):
 * - pixel ratio capped at 1.5 and stepped further down under sustained load;
 * - one shared unit-sphere geometry per body class, scaled per instance;
 * - dashed-link distances update in place — zero per-frame allocations;
 * - the backdrop is fully static; ambient life is the damped camera only;
 * - `dispose()` frees renderer, geometries, materials and every texture.
 *
 * DOM labels are positioned by projecting body anchors each frame, keeping
 * text crisp and accessible while the sky itself stays on the GPU.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { StarfieldTone } from './starfield-motion';
import { SCENE_STAGE_RADIUS, type SceneBody, type StarfieldSceneModel } from './starfield-scene-model';
import { StarfieldTextureSet } from './starfield-textures';

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
/** Reference-style readable orbit line color (q-jade/solar-system). */
const ORBIT_LINE_COLOR = 0x8cb8ce;
const MAX_FRAME_DT = 0.1;

/**
 * Adaptive resolution ladder: start at 1.5 (never 2 — HiDPI full-res quadruples
 * fragment work for no perceptible gain on a starfield) and step down when the
 * frame budget is missed for a sustained stretch. Never steps back up, so the
 * sky cannot oscillate.
 */
const PIXEL_RATIO_STEPS = [1.5, 1.25, 1] as const;
/** A frame slower than this (≈38 fps) counts against the budget. */
const SLOW_FRAME_S = 0.026;
const SLOW_FRAMES_BEFORE_STEP = 60;

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
/* Procedural textures (instant fallbacks; real maps stream in async)  */
/* ------------------------------------------------------------------ */

function radialGlowTexture(inner: string, outer = 'rgba(0,0,0,0)'): THREE.CanvasTexture {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d')!;
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, inner);
  gradient.addColorStop(0.35, inner.replace(/[\d.]+\)$/, '0.35)'));
  gradient.addColorStop(1, outer);
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Soft horizontal bands + hash noise: a cheap believable gas surface. */
function bandedSurfaceTexture(seed: string): THREE.CanvasTexture {
  const width = 256;
  const height = 128;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d')!;
  const random = seededRandom(`${seed}:surface`);
  context.fillStyle = '#8892aa';
  context.fillRect(0, 0, width, height);
  let y = 0;
  while (y < height) {
    const bandHeight = 6 + Math.floor(random() * 18);
    const lightness = 52 + Math.floor(random() * 34);
    context.fillStyle = `hsl(222 18% ${lightness}%)`;
    context.fillRect(0, y, width, bandHeight);
    y += bandHeight;
  }
  context.globalAlpha = 0.16;
  for (let index = 0; index < 320; index += 1) {
    const lightness = 34 + Math.floor(random() * 52);
    context.fillStyle = `hsl(222 22% ${lightness}%)`;
    context.fillRect(random() * width, random() * height, 3 + random() * 14, 1 + random() * 3);
  }
  context.globalAlpha = 1;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}

function softDotTexture(): THREE.CanvasTexture {
  return radialGlowTexture('rgba(232,239,255,1)');
}

/**
 * Approximate spectral-type distribution (ported from the reference):
 * mostly warm K/M dwarfs, a few hot blue-white giants. Gives the sphere a
 * believable astronomic color mix instead of a uniform blue haze.
 */
const STAR_SPECTRA = [
  { weight: 0.04, r: 0.75, g: 0.85, b: 1.0 },
  { weight: 0.08, r: 0.9, g: 0.95, b: 1.0 },
  { weight: 0.12, r: 1.0, g: 1.0, b: 0.8 },
  { weight: 0.4, r: 1.0, g: 0.85, b: 0.6 },
  { weight: 0.36, r: 1.0, g: 0.7, b: 0.5 },
] as const;

function pickSpectrum(roll: number): (typeof STAR_SPECTRA)[number] {
  let cumulative = 0;
  for (const spectrum of STAR_SPECTRA) {
    cumulative += spectrum.weight;
    if (roll < cumulative) return spectrum;
  }
  return STAR_SPECTRA[STAR_SPECTRA.length - 1]!;
}

/* ------------------------------------------------------------------ */
/* Runtime bookkeeping                                                 */
/* ------------------------------------------------------------------ */

interface BodyRuntime {
  body: SceneBody;
  orbitGroup: THREE.Group;
  carrier: THREE.Group;
  anchor: THREE.Group;
  mesh: THREE.Mesh;
  glow: THREE.Sprite;
  glowBaseScale: number;
  statusRing: THREE.Object3D | null;
  statusRingMaterial: THREE.Material | null;
  trail: THREE.Line | null;
  angleRad: number;
  pulseSeed: number;
}

interface CenterRuntime {
  mesh: THREE.Mesh;
  group: THREE.Group;
  glow: THREE.Sprite;
  glowBaseScale: number;
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
  /** Preallocated dashed-line distance attribute, updated in place. */
  lineDistances: THREE.BufferAttribute | null;
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
  private readonly onContextLost: (() => void) | undefined;
  private readonly clock = new THREE.Clock();
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly worldPosition = new THREE.Vector3();
  private readonly linkFrom = new THREE.Vector3();
  private readonly linkTo = new THREE.Vector3();

  private readonly glowTexture = radialGlowTexture('rgba(255,255,255,0.9)');
  private readonly dotTexture = softDotTexture();
  /** Async real-map pool; owns disposal of every streamed texture. */
  private readonly textures = new StarfieldTextureSet();
  /** Shared unit spheres, scaled per instance — one GPU buffer per class. */
  private readonly bodyUnitSphere = new THREE.SphereGeometry(1, 28, 20);
  private readonly centerUnitSphere = new THREE.SphereGeometry(1, 48, 32);

  private modelRoot = new THREE.Group();
  private backdropRoot = new THREE.Group();
  private bodies: BodyRuntime[] = [];
  private center: CenterRuntime | null = null;
  private links: LinkRuntime[] = [];
  private pickTargets: THREE.Object3D[] = [];
  private anchorById = new Map<string, THREE.Object3D>();
  private labelById = new Map<string, HTMLElement>();
  private backdropSeed = '';

  private frameHandle = 0;
  private running = false;
  private reducedMotion = false;
  private dirty = true;
  private elapsedS = 0;
  private viewWidth = 1;
  private viewHeight = 1;
  private pixelRatioStep = 0;
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
    this.onContextLost = options.onContextLost;
    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setClearColor(SPACE_CLEAR, 1);
    this.scene.fog = new THREE.FogExp2(SPACE_CLEAR, 0.011);

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

    this.scene.add(new THREE.AmbientLight(0x37456b, 0.9));
    const key = new THREE.DirectionalLight(0xdfe8ff, 1.6);
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
    this.rebuildModel(model);
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
    this.applyViewport();
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
    this.bodyUnitSphere.dispose();
    this.centerUnitSphere.dispose();
    this.glowTexture.dispose();
    this.dotTexture.dispose();
    this.textures.dispose();
    this.renderer.dispose();
  }

  /* ------------------------------------------------------- backdrop -- */

  /**
   * Static deep space: a spectral star sphere plus a tilted milky-way band
   * (both ported from the reference at a reduced particle budget) and a few
   * nebula sprites. Nothing here updates per frame — ambient life comes from
   * the slowly auto-rotating camera, so an idle sky costs no CPU integration.
   */
  private rebuildBackdrop(model: StarfieldSceneModel): void {
    this.disposeSubtree(this.backdropRoot);
    this.backdropRoot.clear();
    const random = seededRandom(`${model.seed}:backdrop`);

    const shells: Array<{ count: number; radius: [number, number]; size: number; opacity: number }> = [
      { count: 1050, radius: [64, 96], size: 0.55, opacity: 0.62 },
      { count: 460, radius: [44, 64], size: 0.85, opacity: 0.78 },
      { count: 220, radius: [28, 44], size: 1.2, opacity: 0.95 },
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
        const spectrum = pickSpectrum(random());
        const brightness = 0.6 + random() * 0.4;
        colors[index * 3] = spectrum.r * brightness;
        colors[index * 3 + 1] = spectrum.g * brightness;
        colors[index * 3 + 2] = spectrum.b * brightness;
      }
      this.backdropRoot.add(this.buildPoints(positions, colors, shell.size, shell.opacity));
    }

    this.backdropRoot.add(this.buildMilkyWayBand(random));

    const nebulaTints = ['rgba(76,118,255,0.55)', 'rgba(148,104,235,0.5)', 'rgba(84,196,222,0.4)'];
    nebulaTints.forEach((tint, index) => {
      const material = new THREE.SpriteMaterial({
        map: radialGlowTexture(tint),
        transparent: true,
        opacity: 0.32,
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

  private buildPoints(
    positions: Float32Array,
    colors: Float32Array,
    size: number,
    opacity: number,
  ): THREE.Points {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return new THREE.Points(geometry, new THREE.PointsMaterial({
      size,
      map: this.dotTexture,
      transparent: true,
      opacity,
      vertexColors: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    }));
  }

  /** Milky-way: stars concentrated on a tilted galactic plane, dust-reddened toward the core. */
  private buildMilkyWayBand(random: () => number): THREE.Points {
    const count = 620;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const tilt = Math.PI / 3;
    for (let index = 0; index < count; index += 1) {
      const distance = 52 + random() * 40;
      const angle = random() * Math.PI * 2;
      const up = (random() - 0.5) * (5 + random() * 4);
      const flatX = distance * Math.cos(angle);
      const flatZ = distance * Math.sin(angle);
      positions[index * 3] = flatX * Math.cos(tilt);
      positions[index * 3 + 1] = flatX * Math.sin(tilt) + up;
      positions[index * 3 + 2] = flatZ;
      const reddish = 0.5 + 0.5 * ((distance - 52) / 40);
      const brightness = 0.5 + random() * 0.5;
      colors[index * 3] = brightness;
      colors[index * 3 + 1] = (0.8 + 0.2 * (1 - reddish)) * brightness;
      colors[index * 3 + 2] = (0.6 + 0.4 * (1 - reddish)) * brightness;
    }
    const points = this.buildPoints(positions, colors, 0.7, 0.8);
    points.name = 'sf-milkyway';
    return points;
  }

  private buildSpiral(random: () => number): THREE.Points {
    const count = 1200;
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
    const points = this.buildPoints(positions, colors, 0.5, 0.5);
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

  private buildCenter(model: StarfieldSceneModel): CenterRuntime {
    const center = model.center!;
    const group = new THREE.Group();
    const toneColor = TONE_COLORS[center.motion.tone];

    let mesh: THREE.Mesh;
    if (center.kind === 'sun') {
      const material = new THREE.MeshBasicMaterial({ color: 0xffe3b0 });
      mesh = new THREE.Mesh(this.centerUnitSphere, material);
      if (center.textureKey) {
        this.textures.get(center.textureKey, (texture) => {
          material.map = texture;
          material.color.set(0xffffff);
          material.needsUpdate = true;
          this.markDirty();
        });
      }
      const light = new THREE.PointLight(0xffc37a, 130, 0, 2);
      group.add(light);
      const corona = new THREE.Sprite(new THREE.SpriteMaterial({
        map: radialGlowTexture('rgba(255,196,106,0.85)'),
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }));
      corona.scale.setScalar(center.size * 5.4);
      group.add(corona);
    } else {
      const material = new THREE.MeshStandardMaterial({
        color: 0x6fa4ec,
        roughness: 0.52,
        metalness: 0.12,
        map: bandedSurfaceTexture(model.seed),
      });
      mesh = new THREE.Mesh(this.centerUnitSphere, material);
      if (center.textureKey) {
        this.textures.get(center.textureKey, (texture) => {
          const previous = material.map;
          material.map = texture;
          material.color.set(0xf3f6ff);
          material.needsUpdate = true;
          if (previous && !previous.userData.sfOwnedBySet) previous.dispose();
          this.markDirty();
        });
      }
      const atmosphere = new THREE.Mesh(
        this.centerUnitSphere,
        new THREE.MeshBasicMaterial({
          color: toneColor,
          transparent: true,
          opacity: 0.16,
          side: THREE.BackSide,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      );
      atmosphere.scale.setScalar(center.size * 1.16);
      group.add(atmosphere);
      group.add(this.buildPlanetRing(center.size * 1.2, center.size * 2.3, 0.34, 0.22));
    }
    mesh.scale.setScalar(center.size);
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

    const material = body.kind === 'star'
      ? new THREE.MeshBasicMaterial({ color: surface })
      : new THREE.MeshStandardMaterial({ color: surface, roughness: 0.6, metalness: 0.08 });
    const mesh = new THREE.Mesh(this.bodyUnitSphere, material);
    mesh.scale.setScalar(body.size);
    mesh.userData.sfBodyId = body.id;
    anchor.add(mesh);

    if (body.kind !== 'star' && body.textureKey) {
      // Moons keep a lightened palette tint over the grayscale lunar map so
      // per-run hue identity survives; planets show their real map colors.
      const mapTint = body.kind === 'moon'
        ? new THREE.Color(surface).lerp(new THREE.Color(0xffffff), 0.55)
        : new THREE.Color(0xffffff);
      this.textures.get(body.textureKey, (texture) => {
        const standard = material as THREE.MeshStandardMaterial;
        standard.map = texture;
        standard.color.copy(mapTint);
        standard.needsUpdate = true;
        this.markDirty();
      });
      if (body.textureKey === 'saturn') {
        anchor.add(this.buildPlanetRing(body.size * 1.25, body.size * 2.15, 0.42, 0.1));
      }
    }

    if (body.kind !== 'star') {
      const atmosphere = new THREE.Mesh(
        this.bodyUnitSphere,
        new THREE.MeshBasicMaterial({
          color: toneColor,
          transparent: true,
          opacity: body.motion.tone === 'muted' ? 0.08 : 0.18,
          side: THREE.BackSide,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      );
      atmosphere.scale.setScalar(body.size * 1.24);
      anchor.add(atmosphere);
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

    let trail: THREE.Line | null = null;
    if (body.motion.working) {
      trail = this.buildTrail(body.orbitRadius, toneColor);
      carrier.add(trail);
    }

    const { statusRing, statusRingMaterial } = this.buildStatusRing(body, toneColor);
    if (statusRing) anchor.add(statusRing);

    this.pickTargets.push(mesh);
    this.bodies.push({
      body,
      orbitGroup,
      carrier,
      anchor,
      mesh,
      glow,
      glowBaseScale,
      statusRing,
      statusRingMaterial,
      trail,
      angleRad: body.phaseRad,
      pulseSeed: body.phaseRad * 7.13,
    });
  }

  /**
   * A Saturn-style ring: RingGeometry with UVs remapped so u follows the
   * radius and v wraps the circumference (reference technique). Starts as a
   * translucent tinted disc and swaps in the real ring-alpha strip when it
   * arrives.
   */
  private buildPlanetRing(innerRadius: number, outerRadius: number, tiltX: number, tiltZ: number): THREE.Mesh {
    const geometry = new THREE.RingGeometry(innerRadius, outerRadius, 64, 1);
    const positions = geometry.attributes.position as THREE.BufferAttribute;
    const uv = geometry.attributes.uv as THREE.BufferAttribute;
    for (let index = 0; index < positions.count; index += 1) {
      const x = positions.getX(index);
      const y = positions.getY(index);
      const radius = Math.hypot(x, y);
      uv.setXY(
        index,
        (radius - innerRadius) / (outerRadius - innerRadius),
        (Math.atan2(y, x) + Math.PI) / (Math.PI * 2),
      );
    }
    uv.needsUpdate = true;
    const material = new THREE.MeshBasicMaterial({
      color: 0x93a1bd,
      transparent: true,
      opacity: 0.28,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(geometry, material);
    ring.rotation.x = -Math.PI / 2 + tiltX;
    ring.rotation.z = tiltZ;
    this.textures.get('saturnRing', (texture) => {
      // v wraps the circumference, so the angular axis must repeat.
      texture.wrapT = THREE.RepeatWrapping;
      texture.wrapS = THREE.ClampToEdgeWrapping;
      texture.needsUpdate = true;
      material.map = texture;
      material.color.set(0xffffff);
      material.opacity = 0.88;
      material.needsUpdate = true;
      this.markDirty();
    });
    return ring;
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
      color: ORBIT_LINE_COLOR,
      transparent: true,
      opacity: working ? 0.42 : 0.22,
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
    positions.setUsage(THREE.DynamicDrawUsage);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', positions);
    const color = link.failed ? TONE_COLORS.attention : link.live ? 0x55c3dd : TONE_COLORS.done;
    const dashed = link.live || link.failed;
    const material = dashed
      ? new THREE.LineDashedMaterial({
          color,
          transparent: true,
          opacity: link.live ? 0.9 : 0.55,
          dashSize: 0.5,
          gapSize: 0.35,
        })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.32 });
    let lineDistances: THREE.BufferAttribute | null = null;
    if (dashed) {
      lineDistances = new THREE.BufferAttribute(new Float32Array(2), 1);
      lineDistances.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute('lineDistance', lineDistances);
    }
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
    this.trackFrameBudget(dt);
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
          runtime.mesh.rotation.y += motion.spinRadPerS * motionDt;
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
   * outliers such as tab switches) and step the pixel-ratio ladder down so
   * the sky yields GPU headroom back to the OS instead of dragging it.
   */
  private trackFrameBudget(dt: number): void {
    if (dt >= MAX_FRAME_DT) return;
    if (dt > SLOW_FRAME_S) {
      this.slowFrames += 1;
    } else {
      this.slowFrames = Math.max(0, this.slowFrames - 2);
    }
    if (this.slowFrames >= SLOW_FRAMES_BEFORE_STEP && this.pixelRatioStep < PIXEL_RATIO_STEPS.length - 1) {
      this.pixelRatioStep += 1;
      this.slowFrames = 0;
      this.applyViewport();
    }
  }

  private applyViewport(): void {
    const cap = PIXEL_RATIO_STEPS[this.pixelRatioStep]!;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, cap));
    this.renderer.setSize(this.viewWidth, this.viewHeight, false);
    this.camera.aspect = this.viewWidth / this.viewHeight;
    this.camera.updateProjectionMatrix();
    this.markDirty();
  }

  private renderOnce(): void {
    this.controls.update();
    this.updateLabels();
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
  }

  private updateLinks(motionDt: number): boolean {
    if (!this.links.length) return false;
    let animated = false;
    for (const link of this.links) {
      const fromObject = this.anchorById.get(link.fromId) ?? this.center?.group;
      const toObject = this.anchorById.get(link.toId);
      if (!fromObject || !toObject) continue;
      fromObject.getWorldPosition(this.linkFrom);
      toObject.getWorldPosition(this.linkTo);
      link.positions.setXYZ(0, this.linkFrom.x, this.linkFrom.y, this.linkFrom.z);
      link.positions.setXYZ(1, this.linkTo.x, this.linkTo.y, this.linkTo.z);
      link.positions.needsUpdate = true;
      const material = link.line.material as THREE.LineDashedMaterial | THREE.LineBasicMaterial;
      if (link.lineDistances && 'dashSize' in material) {
        // Two-point dashed line: shift the lineDistance values in place so
        // the dash pattern visibly flows from source to target while live.
        if (link.live && motionDt > 0) {
          link.dashShift = (link.dashShift + motionDt * 1.6) % (material.dashSize + material.gapSize);
          animated = true;
        }
        const length = this.linkFrom.distanceTo(this.linkTo);
        link.lineDistances.setX(0, -link.dashShift);
        link.lineDistances.setX(1, length - link.dashShift);
        link.lineDistances.needsUpdate = true;
      }
      if (link.packet) {
        const t = (this.elapsedS * 0.32 + link.packetSeed) % 1;
        link.packet.position.lerpVectors(this.linkFrom, this.linkTo, t);
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
    this.onContextLost?.();
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
      if (
        mesh.geometry
        && mesh.geometry !== this.bodyUnitSphere
        && mesh.geometry !== this.centerUnitSphere
      ) {
        mesh.geometry.dispose();
      }
      const material = mesh.material;
      if (Array.isArray(material)) {
        for (const item of material) this.disposeMaterial(item);
      } else if (material) {
        this.disposeMaterial(material);
      }
    });
  }

  private disposeMaterial(material: THREE.Material): void {
    const textured = material as THREE.Material & { map?: THREE.Texture | null };
    const map = textured.map;
    // Textures owned by the shared pool are disposed exactly once by the
    // pool itself; per-material procedural canvases die with their material.
    if (
      map
      && map !== this.glowTexture
      && map !== this.dotTexture
      && !map.userData.sfOwnedBySet
    ) {
      map.dispose();
    }
    material.dispose();
  }
}
