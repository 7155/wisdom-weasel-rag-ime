import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { galaxyHash, type ProjectGalaxyBody, type ProjectGalaxyModel } from './project-galaxy-model';
import { starfieldEntrance } from './project-galaxy-entrance';
import { advanceOrbit, createOrbit, orbitPath, type OrbitState } from './project-galaxy-physics';
import { createPaintedGalaxy } from './project-galaxy-paint';
import { placeGalaxyLabels, type GalaxyLabelAnchor } from './project-galaxy-labels';
import * as shaders from './project-galaxy-shaders';

type Planet = { body: ProjectGalaxyBody; group: THREE.Group; sphere: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>; spin: number; orbit: THREE.Line; physics: OrbitState };
const coreRadius = .78;
const cameraDistance = Math.hypot(24, 34);
const nodeColor = (body: ProjectGalaxyBody) => body.motion.tone === 'attention' ? '#f4ba74' : body.motion.working ? '#b6e5d5' : '#f2d392';

/** A new, self-contained project universe. It owns only GPU resources and
 * camera navigation; Session identity, activity, progress and files stay above. */
export class ProjectGalaxyStage {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(42, 1, .1, 240);
  private readonly controls: OrbitControls;
  private readonly sphereGeometry = new THREE.SphereGeometry(1, 40, 28);
  private readonly planeGeometry = new THREE.PlaneGeometry(2, 2);
  private readonly painting: ReturnType<typeof createPaintedGalaxy>;
  private coreStar: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial> | undefined;
  private focus: { from: THREE.Vector3; to: THREE.Vector3; elapsed: number } | null = null;
  private readonly planets = new Map<string, Planet>();
  private readonly labels = new Map<string, HTMLElement>();
  private readonly labelSizes = new Map<string, { width: number; height: number }>();
  private readonly leaders = new Map<string, SVGLineElement>();
  private hoverPointer: THREE.Vector2 | null = null;
  private hovered: string | null = null;
  private readonly pickTargets: THREE.Object3D[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly scratch = new THREE.Vector3();
  private readonly origin = new THREE.Vector3();
  private readonly particleMaterials: THREE.ShaderMaterial[] = [];
  private readonly orbitRoot = new THREE.Group();
  private width = 1;
  private height = 1;
  private fit = 1;
  private portrait = false;
  private sizeDirty = true;
  private visible = false;
  private reduced = false;
  private disposed = false;
  private frameId = 0;
  private singleFrameId = 0;
  private lastFrame = 0;
  private elapsed = 0;
  private simulationTime = 0;
  private simulationSpeed = 1;
  private quality = 1;
  private slowFrames = 0;
  private selected: string | null = null;
  private down: { x: number; y: number } | null = null;
  private readonly seed: number;

  constructor(private readonly options: { canvas: HTMLCanvasElement; labels: HTMLElement; seed: string; onPick(id: string | null): void; onLost(): void }) {
    this.seed = galaxyHash(options.seed);
    this.painting = createPaintedGalaxy(this.seed);
    this.renderer = new THREE.WebGLRenderer({ canvas: options.canvas, antialias: true, alpha: false, powerPreference: 'default' });
    this.renderer.setClearColor(0x050916, 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    this.camera.position.set(0, 24, 34);
    this.camera.lookAt(0, 0, 0);
    this.controls = new OrbitControls(this.camera, options.canvas);
    this.controls.target.set(0, 0, 0);
    this.controls.enablePan = false;
    this.controls.enableDamping = true;
    this.controls.dampingFactor = .08;
    this.controls.minDistance = 26;
    this.controls.maxDistance = 70;
    this.controls.minPolarAngle = .18;
    this.controls.maxPolarAngle = 1.12;
    this.controls.addEventListener('change', this.requestDraw);
    this.scene.add(this.painting.group, this.orbitRoot);
    this.buildUniverse();
    options.canvas.addEventListener('pointerdown', this.pointerDown);
    options.canvas.addEventListener('pointerup', this.pointerUp);
    options.canvas.addEventListener('pointermove', this.pointerMove);
    options.canvas.addEventListener('pointerleave', this.pointerLeave);
    options.canvas.addEventListener('webglcontextlost', this.contextLost);
  }

  private random() {
    let state = this.seed || 1;
    return () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 4294967296; };
  }

  private buildUniverse() {
    const random = this.random();
    const count = 2200;
    const positions = new Float32Array(count * 3), colors = new Float32Array(count * 3), sizes = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const radius = 40 + random() * 35, angle = random() * Math.PI * 2, polar = Math.acos(random() * 2 - 1);
      positions.set([radius * Math.sin(polar) * Math.cos(angle), radius * Math.cos(polar), radius * Math.sin(polar) * Math.sin(angle)], i * 3);
      const light = .2 + random() * .65;
      colors.set([light * .4, light * .7, light], i * 3);
      sizes[i] = i % 19 ? .25 + random() * .2 : .65;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    const material = new THREE.ShaderMaterial({ vertexShader: shaders.pointVertex, fragmentShader: shaders.pointFragment,
      uniforms: { uRatio: { value: 1 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    this.particleMaterials.push(material);
    this.scene.add(new THREE.Points(geometry, material));
    const core = new THREE.Mesh(this.sphereGeometry, new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false, transparent: true, opacity: 0 }));
    core.scale.setScalar(coreRadius);
    core.userData.galaxyId = 'center';
    this.scene.add(core);
    this.pickTargets.push(core);
    this.coreStar = new THREE.Mesh(this.planeGeometry, this.starMaterial('#ffdc8c', .37, false));
    this.coreStar.scale.setScalar(1.45);
    this.coreStar.position.y = .2;
    this.scene.add(this.coreStar);
  }

  private starMaterial(color: string, seed: number, working: boolean) {
    return new THREE.ShaderMaterial({ vertexShader: shaders.starVertex, fragmentShader: shaders.starFragment,
      uniforms: { uColor: { value: new THREE.Color(color) }, uSelected: { value: 0 }, uTime: { value: 0 }, uWorking: { value: working ? 1 : 0 }, uSeed: { value: seed } },
      transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending });
  }

  setModel(model: ProjectGalaxyModel) {
    const ids = new Set(model.bodies.map((body) => body.id));
    for (const [id, planet] of this.planets) if (!ids.has(id)) {
      this.scene.remove(planet.group);
      this.disposeObject(planet.group);
      this.orbitRoot.remove(planet.orbit);
      this.disposeObject(planet.orbit);
      this.planets.delete(id);
    }
    this.pickTargets.splice(1);
    for (const body of model.bodies) {
      let planet = this.planets.get(body.id);
      if (!planet) {
        planet = this.createPlanet(body);
        this.planets.set(body.id, planet);
        this.scene.add(planet.group);
        this.orbitRoot.add(planet.orbit);
      } else if (planet.body.orbitRadius !== body.orbitRadius || planet.body.phaseRad !== body.phaseRad || planet.body.inclinationRad !== body.inclinationRad || planet.body.eccentricity !== body.eccentricity) {
        planet.physics = createOrbit(body);
        const path = planet.orbit.geometry.getAttribute('position') as THREE.BufferAttribute;
        orbitPath(body, path.array as Float32Array);
        path.needsUpdate = true;
        planet.orbit.geometry.computeBoundingSphere();
      }
      planet.body = body;
      planet.sphere.material.uniforms.uColor!.value.set(nodeColor(body));
      planet.sphere.material.uniforms.uWorking!.value = body.motion.working ? 1 : 0;
      this.pickTargets.push(planet.sphere);
    }
    this.labels.clear();
    this.options.labels.querySelectorAll<HTMLElement>('[data-galaxy-body]').forEach((label) => this.labels.set(label.dataset.galaxyBody!, label));
    this.leaders.clear();
    this.options.labels.querySelectorAll<SVGLineElement>('[data-galaxy-leader]').forEach((line) => this.leaders.set(line.dataset.galaxyLeader!, line));
    this.measureLabels();
    this.placePlanets(0);
    this.draw();
  }

  private createPlanet(body: ProjectGalaxyBody): Planet {
    const material = this.starMaterial(nodeColor(body), galaxyHash(body.id) % 1000 / 100, body.motion.working);
    const sphere = new THREE.Mesh(this.planeGeometry, material);
    sphere.userData.galaxyId = body.id;
    const group = new THREE.Group();
    group.add(sphere);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(orbitPath(body), 3));
    const orbit = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: '#baad86', transparent: true, opacity: .15, depthWrite: false }));
    orbit.userData.galaxyOrbit = true;
    return { body, group, sphere, spin: body.phaseRad, orbit, physics: createOrbit(body) };
  }

  setSelected(id: string | null) {
    if (this.selected === id) return;
    this.selected = id;
    // Inspection anchors every target and label, while real Runtime updates continue.
    if (id) this.elapsed = Math.max(this.elapsed, 2);
    const to = (this.planets.get(id ?? '')?.group.position ?? this.origin).clone().multiplyScalar(.42);
    if (this.reduced) {
      this.camera.position.add(to.clone().sub(this.controls.target));
      this.controls.target.copy(to);
      this.controls.update();
    } else this.focus = { from: this.controls.target.clone(), to, elapsed: 0 };
    this.requestDraw();
  }
  setMotion(visible: boolean, reduced: boolean, speed = 1) {
    this.visible = visible;
    this.simulationSpeed = Math.max(0, Math.min(4, Number.isFinite(speed) ? speed : 1));
    this.reduced = reduced || this.simulationSpeed === 0;
    this.controls.enableDamping = !this.reduced;
    cancelAnimationFrame(this.frameId);
    cancelAnimationFrame(this.singleFrameId);
    this.frameId = this.singleFrameId = 0;
    this.lastFrame = 0;
    if (visible) {
      this.placePlanets(0);
      this.draw();
      if (!this.reduced) this.frameId = requestAnimationFrame(this.frame);
    }
  }
  resize(width: number, height: number) {
    if (width < 2 || height < 2 || this.disposed) return;
    this.width = width; this.height = height;
    this.camera.aspect = width / height;
    const nextFit = Math.max(1, 20.6 / (Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * this.camera.aspect * .88 * cameraDistance));
    const offset = this.camera.position.clone().sub(this.controls.target).multiplyScalar(nextFit / this.fit);
    const portrait = width / height < .85;
    if (portrait !== this.portrait) offset.copy(new THREE.Vector3(0, portrait ? 1 : 24, portrait ? .3 : 34).normalize().multiplyScalar(offset.length()));
    this.portrait = portrait;
    this.camera.position.copy(this.controls.target).add(offset);
    this.fit = nextFit;
    this.controls.minDistance = 26 * this.fit;
    this.controls.maxDistance = 70 * this.fit;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.measureLabels();
    this.sizeDirty = true;
    this.draw();
  }
  private resolution() {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(1_800_000 / (this.width * this.height))) * this.quality;
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(this.width, this.height, false);
    this.painting.resize(ratio*this.height/(2*Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2))));
    this.particleMaterials.forEach((material) => { material.uniforms.uRatio!.value = ratio; });
    this.sizeDirty = false;
  }
  private measureLabels() {
    this.labelSizes.clear();
    for (const [id, label] of this.labels) this.labelSizes.set(id, { width: label.offsetWidth || 152, height: label.offsetHeight || 46 });
  }
  private placePlanets(dt: number) {
    let index = 0;
    if (this.coreStar) {
      this.coreStar.visible = this.selected === 'center';
      this.coreStar.material.uniforms.uSelected!.value = this.selected === 'center' ? 1 : 0;
    }
    for (const planet of this.planets.values()) {
      const { body, group } = planet;
      const entrance = starfieldEntrance(this.elapsed, index++, this.reduced);
      if (!this.reduced && !this.selected && this.elapsed > 1.8) {
        advanceOrbit(planet.physics, dt * this.simulationSpeed * .15);
        planet.spin += dt * this.simulationSpeed * body.spinRadPerS;
      }
      const { x, y, z } = planet.physics;
      const cos = Math.cos(entrance.phase), sin = Math.sin(entrance.phase);
      group.position.set((x * cos - z * sin) * entrance.radius, y * entrance.radius, (x * sin + z * cos) * entrance.radius);
      group.scale.setScalar(body.size * entrance.scale);
      const selected = body.id === this.selected;
      planet.sphere.material.uniforms.uSelected!.value = selected ? 1 : 0;
      planet.sphere.material.uniforms.uTime!.value = this.simulationTime;
      planet.orbit.visible = selected;
    }
  }
  private readonly frame = (now: number) => {
    if (this.disposed || !this.visible || this.reduced) return;
    this.frameId = requestAnimationFrame(this.frame);
    if (this.lastFrame && now - this.lastFrame < 32) return;
    const dt = this.lastFrame ? Math.min(.08, (now - this.lastFrame) / 1000) : 0;
    this.lastFrame = now;
    this.elapsed += dt;
    this.simulationTime += dt * this.simulationSpeed;
    const started = performance.now();
    this.placePlanets(dt);
    this.painting.update(this.simulationTime);
    if (this.focus) {
      this.focus.elapsed += dt;
      const t = Math.min(1, this.focus.elapsed / .26);
      const next = this.scratch.lerpVectors(this.focus.from, this.focus.to, 1 - Math.pow(1 - t, 3));
      this.camera.position.add(next.clone().sub(this.controls.target));
      this.controls.target.copy(next);
      if (t === 1) this.focus = null;
    }
    this.controls.update();
    this.draw();
    const cost = performance.now() - started;
    this.slowFrames = cost > 21 || dt > .055 ? this.slowFrames + 1 : Math.max(0, this.slowFrames - 1);
    if (this.slowFrames > 45 && this.quality > .65) { this.quality *= .8; this.slowFrames = 0; this.resolution(); }
  };
  private readonly requestDraw = () => {
    if (this.disposed || !this.visible || !this.reduced || this.singleFrameId) return;
    this.singleFrameId = requestAnimationFrame(() => { this.singleFrameId = 0; this.placePlanets(0); this.draw(); });
  };
  private draw() {
    if (this.disposed || !this.visible) return;
    if (this.sizeDirty) this.resolution();
    if (this.coreStar) this.coreStar.quaternion.copy(this.camera.quaternion);
    for (const planet of this.planets.values()) {
      planet.sphere.quaternion.copy(this.camera.quaternion);
      planet.sphere.rotateZ(planet.spin);
    }
    this.scene.updateMatrixWorld(true);
    this.camera.updateMatrixWorld(true);
    const anchors: GalaxyLabelAnchor[] = [];
    const projectLabel = (id: string, point: THREE.Vector3, size: number) => {
      const label = this.labels.get(id);
      if (!label) return;
      this.scratch.copy(point).applyMatrix4(this.camera.matrixWorldInverse);
      const radiusPx = size * this.height / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * Math.max(.1, -this.scratch.z));
      this.scratch.copy(point).project(this.camera);
      const x = (this.scratch.x * .5 + .5) * this.width, y = (-this.scratch.y * .5 + .5) * this.height;
      const visible = this.scratch.z < 1 && x > 0 && x < this.width && y > 80 && y < this.height - 70;
      label.style.visibility = visible ? 'visible' : 'hidden';
      const line = this.leaders.get(id);
      if (line) line.style.visibility = 'hidden';
      if (visible) anchors.push({ id, x, y, radius: radiusPx, ...(this.labelSizes.get(id) ?? { width: 152, height: 46 }) });
    };
    projectLabel('center', this.origin, coreRadius);
    // The translucent brush halo is much wider than the visible star core.
    for (const planet of this.planets.values()) projectLabel(planet.body.id, planet.group.position, planet.group.scale.x * .42);
    const hovered = this.hoverPointer ? anchors.reduce<{ id: string | null; distance: number }>((nearest, anchor) => {
      const distance = Math.hypot(this.hoverPointer!.x - anchor.x, this.hoverPointer!.y - anchor.y);
      return distance < nearest.distance ? { id: anchor.id, distance } : nearest;
    }, { id: null, distance: 62 }).id : null;
    if (hovered !== this.hovered) {
      this.hovered = hovered;
      for (const [id, label] of this.labels) label.dataset.near = String(id === hovered);
      this.options.canvas.style.cursor = hovered ? 'pointer' : 'grab';
    }
    for (const placement of placeGalaxyLabels(anchors, this.width, this.height, this.selected)) {
      const { id, x, y, radius, left, top, width, height } = placement;
      this.labels.get(id)!.style.transform = `translate(${left.toFixed(1)}px, ${top.toFixed(1)}px)`;
      const line = this.leaders.get(id);
      if (!line) continue;
      const endX = Math.max(left, Math.min(left + width, x)), endY = Math.max(top, Math.min(top + height, y));
      const distance = Math.hypot(endX - x, endY - y);
      if (distance < radius + 25 || (id !== this.selected && id !== this.hovered)) continue;
      line.style.visibility = 'visible';
      line.setAttribute('x1', (x + (endX - x) * (radius + 5) / distance).toFixed(1));
      line.setAttribute('y1', (y + (endY - y) * (radius + 5) / distance).toFixed(1));
      line.setAttribute('x2', endX.toFixed(1)); line.setAttribute('y2', endY.toFixed(1));
    }
    this.renderer.render(this.scene, this.camera);
  }
  private readonly pointerDown = (event: PointerEvent) => { this.focus = null; this.down = { x: event.clientX, y: event.clientY }; };
  private readonly pointerMove = (event: PointerEvent) => {
    const rect = this.options.canvas.getBoundingClientRect();
    this.hoverPointer ??= new THREE.Vector2();
    this.hoverPointer.set(event.clientX - rect.left, event.clientY - rect.top);
    this.requestDraw();
  };
  private readonly pointerLeave = () => { this.hoverPointer = null; this.requestDraw(); };
  private readonly pointerUp = (event: PointerEvent) => {
    if (!this.down || Math.hypot(event.clientX - this.down.x, event.clientY - this.down.y) > 6) return;
    this.down = null;
    const rect = this.options.canvas.getBoundingClientRect();
    this.pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.pickTargets, false)[0];
    this.options.onPick(hit ? String(hit.object.userData.galaxyId) : null);
  };
  private readonly contextLost = (event: Event) => { event.preventDefault(); this.options.onLost(); };
  private disposeObject(root: THREE.Object3D) {
    const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
    root.traverse((object) => {
      const { geometry, material } = object as THREE.Mesh;
      if (geometry && geometry !== this.sphereGeometry && geometry !== this.planeGeometry) geometries.add(geometry);
      if (material) (Array.isArray(material) ? material : [material]).forEach((entry) => materials.add(entry));
    });
    geometries.forEach((geometry) => geometry.dispose());
    materials.forEach((material) => material.dispose());
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.frameId); cancelAnimationFrame(this.singleFrameId);
    this.controls.removeEventListener('change', this.requestDraw); this.controls.dispose();
    this.options.canvas.removeEventListener('pointerdown', this.pointerDown);
    this.options.canvas.removeEventListener('pointerup', this.pointerUp);
    this.options.canvas.removeEventListener('pointermove', this.pointerMove);
    this.options.canvas.removeEventListener('pointerleave', this.pointerLeave);
    this.options.canvas.removeEventListener('webglcontextlost', this.contextLost);
    this.disposeObject(this.scene);
    this.sphereGeometry.dispose(); this.planeGeometry.dispose();
    this.renderer.dispose(); this.renderer.forceContextLoss();
    this.labels.clear(); this.labelSizes.clear(); this.leaders.clear(); this.planets.clear();
  }
}
