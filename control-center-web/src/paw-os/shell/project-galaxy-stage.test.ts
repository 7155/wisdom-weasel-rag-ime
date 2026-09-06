import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectGalaxyStage } from './project-galaxy-stage';
import { projectGalaxyScene } from './project-galaxy-model';
import type { WayfinderWorkItem } from './wayfinder-work-projection';

// Keep the real scene graph, geometry, materials and projection math. Only the
// GPU boundary and browser controls are replaced in this lifecycle contract.
const gpu = vi.hoisted(() => ({ render: vi.fn(), setSize: vi.fn(), dispose: vi.fn(), forceContextLoss: vi.fn() }));
vi.mock('three', async (original) => ({
  ...await original<typeof import('three')>(),
  WebGLRenderer: class {
    setClearColor = vi.fn(); setPixelRatio = vi.fn();
    shadowMap = { enabled: false, type: 0 };
    render = gpu.render; setSize = gpu.setSize; dispose = gpu.dispose; forceContextLoss = gpu.forceContextLoss;
  },
}));
vi.mock('three/addons/controls/OrbitControls.js', () => ({ OrbitControls: class {
  target = new THREE.Vector3();
  constructor(private camera: THREE.Camera) {}
  addEventListener() {} removeEventListener() {} update() { this.camera.lookAt(this.target); } dispose() {}
} }));

const item: WayfinderWorkItem = { id: 's1', key: 'session:s1', projectKey: 'paw', project: 'PAW', workspaceRoots: [],
  kind: 'session', title: '真实任务', updatedAtMs: 0, activity: 'running', runtimeRunning: true, statusLabel: '进行中', detail: '正在读取项目', agents: [], repeats: [] };
const model = () => projectGalaxyScene('paw', 'PAW', [item]);
const frames = new Map<number, FrameRequestCallback>();
let nextFrame = 0;
const stages: ProjectGalaxyStage[] = [];

function setup(labels = document.createElement('div'), canvas = document.createElement('canvas')) {
  const stage = new ProjectGalaxyStage({ canvas, labels, seed: 'paw', onPick: vi.fn(), onLost: vi.fn() });
  stages.push(stage);
  stage.resize(1200, 800);
  stage.setModel(model());
  stage.setMotion(true, false);
  return stage;
}

function orbits() {
  const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
  const lines: THREE.Line[] = [];
  scene.traverse((object) => { if (object instanceof THREE.Line && object.userData.galaxyOrbit) lines.push(object); });
  return lines;
}

beforeEach(() => {
  vi.clearAllMocks(); frames.clear(); nextFrame = 0;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
});
afterEach(() => { stages.splice(0).forEach((stage) => stage.dispose()); vi.unstubAllGlobals(); });

describe('project galaxy rendering budget', () => {
  it('reveals the approached star while paused and clears the reveal on pointer leave', () => {
    const labels = document.createElement('div'), canvas = document.createElement('canvas');
    const label = document.createElement('button');
    label.dataset.galaxyBody = item.key; labels.append(label);
    const stage = setup(labels, canvas); stage.setMotion(true, true);
    const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
    const camera = gpu.render.mock.lastCall![1] as THREE.Camera;
    const target = scene.getObjectsByProperty('type', 'Mesh').find((mesh) => mesh.userData.galaxyId === item.key)!;
    const point = target.getWorldPosition(new THREE.Vector3()).project(camera);
    const drawRequestedFrame = () => {
      const [id, callback] = [...frames][0]!; frames.delete(id); callback(1000);
    };
    canvas.dispatchEvent(new MouseEvent('pointermove', { clientX: (point.x*.5+.5)*1200, clientY: (-point.y*.5+.5)*800 }));
    drawRequestedFrame();
    expect(label.dataset.near).toBe('true');
    expect(canvas.style.cursor).toBe('pointer');
    canvas.dispatchEvent(new MouseEvent('pointerleave')); drawRequestedFrame();
    expect(label.dataset.near).toBe('false');
    expect(canvas.style.cursor).toBe('grab');
    expect(frames.size).toBe(0);
    stage.dispose(); canvas.dispatchEvent(new MouseEvent('pointermove'));
    expect(frames.size).toBe(0);
  });

  it('keeps real selection targets on screen through portrait and desktop resize', () => {
    const stage = setup();
    stage.setModel(projectGalaxyScene('paw', 'PAW', Array.from({ length: 12 }, (_, i) => ({ ...item, id: `s${i}`, key: `session:s${i}` }))));
    stage.setMotion(true, true);
    for (const [width, height] of [[1200, 800], [390, 844], [1200, 800]]) {
      stage.resize(width!, height!);
      const camera = gpu.render.mock.lastCall![1] as THREE.Camera;
      const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
      const targets = scene.getObjectsByProperty('type', 'Mesh').filter((mesh) => mesh.userData.galaxyId);
      expect(targets).toHaveLength(13);
      for (const target of targets) {
        const point = target.getWorldPosition(new THREE.Vector3()).project(camera);
        expect(Math.abs(point.x)).toBeLessThan(.93);
        expect(Math.abs(point.y)).toBeLessThan(.85);
      }
    }
  });

  it('bounds dense dust and painted geometry, animates without uploads, and releases every layer once', () => {
    const stage = setup();
    const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
    const painting = scene.getObjectByName('painted-spiral-galaxy')!;
    expect(painting.children.length).toBeLessThanOrEqual(4);
    const meshes = painting.children.filter((object) => (object as THREE.Mesh).geometry instanceof THREE.InstancedBufferGeometry) as THREE.Mesh<THREE.InstancedBufferGeometry, THREE.ShaderMaterial>[];
    expect(meshes.length).toBeLessThanOrEqual(2);
    expect(meshes.reduce((sum, mesh) => sum + mesh.geometry.instanceCount * mesh.geometry.index!.count / 3, 0)).toBeLessThanOrEqual(50_000);
    const layers: (THREE.Mesh<THREE.BufferGeometry, THREE.ShaderMaterial> | THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>)[] = [];
    painting.traverse((object) => { if (object instanceof THREE.Mesh || object instanceof THREE.Points) layers.push(object); });
    expect(layers.length).toBeLessThanOrEqual(5);
    const dust = layers.filter((object) => object instanceof THREE.Points && object.userData.galaxyDust);
    expect(dust).toHaveLength(2);
    const grainCount = dust.reduce((sum, points) => sum + points.geometry.getAttribute('position').count, 0);
    expect(grainCount).toBeGreaterThanOrEqual(100_000);
    expect(grainCount).toBeLessThanOrEqual(160_000);
    const dustBytes = dust.reduce((sum, points) => sum + Object.values(points.geometry.attributes).reduce((total, attribute) => total + attribute.array.byteLength, 0), 0);
    expect(dustBytes).toBeLessThanOrEqual(8 * 1024 * 1024);
    const originalPixelScale = dust.map((points) => points.material.uniforms.uPixelScale!.value as number);
    const resources = layers.map((mesh) => {
      const geometryDispose = vi.fn(), materialDispose = vi.fn();
      mesh.geometry.addEventListener('dispose', geometryDispose);
      mesh.material.addEventListener('dispose', materialDispose);
      expect(Object.values(mesh.material.uniforms).some(({ value }) => value instanceof THREE.Texture)).toBe(false);
      const attributes = Object.values(mesh.geometry.attributes) as THREE.BufferAttribute[];
      return { mesh, geometry: mesh.geometry, attributes, versions: attributes.map((attribute) => attribute.version), geometryDispose, materialDispose };
    });
    let now = 0;
    for (let i = 0; i < 30; i++) {
      const [id, callback] = [...frames][0]!;
      frames.delete(id); callback(now += 40);
    }
    stage.setModel(model());
    stage.resize(600, 400);
    dust.forEach((points, index) => expect(points.material.uniforms.uPixelScale!.value).toBeCloseTo(originalPixelScale[index]! / 2));
    for (const resource of resources) {
      expect(resource.mesh.geometry).toBe(resource.geometry);
      expect(Object.values(resource.mesh.geometry.attributes)).toEqual(resource.attributes);
      expect(resource.attributes.map((attribute) => attribute.version)).toEqual(resource.versions);
      expect(resource.mesh.material.uniforms.uTime!.value).toBeGreaterThan(0);
      expect(resource.geometryDispose).not.toHaveBeenCalled();
    }
    stage.dispose(); stage.dispose();
    for (const resource of resources) {
      expect(resource.geometryDispose).toHaveBeenCalledOnce();
      expect(resource.materialDispose).toHaveBeenCalledOnce();
    }
  });

  it('anchors the selected target while inspecting, then resumes its existing orbit', () => {
    const stage = setup();
    let now = 0;
    const tick = () => {
      const [id, callback] = [...frames][0]!;
      frames.delete(id); callback(now += 40);
    };
    for (let i = 0; i < 60; i++) tick();
    const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
    const sphere = scene.getObjectsByProperty('type', 'Mesh').find((mesh) => mesh.userData.galaxyId === item.key)!;
    const start = sphere.parent!.position.clone();
    stage.setSelected(item.key);
    for (let i = 0; i < 20; i++) tick();
    expect(sphere.parent!.position.distanceTo(start)).toBeLessThan(.0001);
    stage.setSelected(null);
    for (let i = 0; i < 20; i++) tick();
    expect(sphere.parent!.position.distanceTo(start)).toBeGreaterThan(.001);
  });

  it('defers GPU drawing and resize while hidden, then renders the latest model when visible', () => {
    const stage = setup();
    expect(gpu.render).toHaveBeenCalled();
    stage.setMotion(false, false);
    gpu.render.mockClear(); gpu.setSize.mockClear();
    const updated = model();
    updated.bodies[0] = { ...updated.bodies[0]!, orbitRadius: 9 };
    stage.setModel(updated);
    stage.resize(800, 600);
    stage.setSelected(item.key);
    expect(gpu.render).not.toHaveBeenCalled();
    expect(gpu.setSize).not.toHaveBeenCalled();
    expect(frames.size).toBe(0);
    stage.setMotion(true, true);
    expect(gpu.render).toHaveBeenCalledOnce();
    expect(gpu.setSize).toHaveBeenLastCalledWith(800, 600, false);
    const scene = gpu.render.mock.lastCall![0] as THREE.Scene;
    const sphere = scene.getObjectsByProperty('type', 'Mesh').find((mesh) => mesh.userData.galaxyId === item.key);
    expect(sphere).toBeDefined();
    expect(sphere!.parent!.position.x).toBeCloseTo(Math.cos(updated.bodies[0]!.phaseRad) * 9);
    expect(frames.size).toBe(0);
  });

  it('retains orbit resources across live progress updates and disposes them on close', () => {
    const stage = setup();
    const first = orbits()[0]!;
    const geometryDisposed = vi.fn();
    const materialDisposed = vi.fn();
    first.geometry.addEventListener('dispose', geometryDisposed);
    (first.material as THREE.Material).addEventListener('dispose', materialDisposed);
    stage.setModel(projectGalaxyScene('paw', 'PAW', [{ ...item, runtimeRunning: false, activity: 'idle', statusLabel: '就绪', detail: '已完成' }]));
    expect(orbits()[0]).toBe(first);
    expect(geometryDisposed).not.toHaveBeenCalled();
    expect(materialDisposed).not.toHaveBeenCalled();
    const updated = model();
    updated.bodies[0] = { ...updated.bodies[0]!, orbitRadius: 9, inclinationRad: .1 };
    stage.setModel(updated);
    expect(orbits()[0]).toBe(first);
    const positions = first.geometry.getAttribute('position');
    expect(Math.hypot(positions.getX(0), positions.getY(0), positions.getZ(0))).toBeCloseTo(9);
    expect(positions.getY(0) / positions.getZ(0)).toBeCloseTo(Math.tan(.1));
    stage.dispose(); stage.dispose();
    expect(geometryDisposed).toHaveBeenCalledOnce();
    expect(materialDisposed).toHaveBeenCalledOnce();
    expect(gpu.dispose).toHaveBeenCalledOnce();
    expect(gpu.forceContextLoss).toHaveBeenCalledOnce();
    expect(frames.size).toBe(0);
  });

  it('releases departed orbit buffers without disposing the remaining planet on the next page', () => {
    const stage = setup();
    const first = orbits()[0]!;
    const materialDisposed = vi.fn();
    const geometryDisposed = vi.fn();
    (first.material as THREE.Material).addEventListener('dispose', materialDisposed);
    first.geometry.addEventListener('dispose', geometryDisposed);
    const second = { ...item, id: 's2', key: 'session:s2' };
    stage.setModel(projectGalaxyScene('paw', 'PAW', [item, second]));
    const retained = orbits()[1]!;
    const retainedDisposed = vi.fn();
    retained.geometry.addEventListener('dispose', retainedDisposed);
    stage.setModel(projectGalaxyScene('paw', 'PAW', [second]));
    expect(orbits()).toEqual([retained]);
    expect(materialDisposed).toHaveBeenCalledOnce();
    expect(geometryDisposed).toHaveBeenCalledOnce();
    expect(retainedDisposed).not.toHaveBeenCalled();
    stage.dispose();
    expect(materialDisposed).toHaveBeenCalledOnce();
    expect(geometryDisposed).toHaveBeenCalledOnce();
    expect(retainedDisposed).toHaveBeenCalledOnce();
  });
});
