import { contourDensity, type ContourMultiPolygon } from 'd3-contour';
import type { ProjectRoom } from './prototype-data';

type DensityPoint = {
  weight: number;
  x: number;
  y: number;
};

export type WayfinderIslandGeometry = {
  contour: string;
  highland: string;
  semanticAnchors: readonly { title: string; x: number; y: number }[];
  shore: string;
  water: string;
};

const ISLAND_WIDTH = 320;
const ISLAND_HEIGHT = 210;

// Each stable Wayfinder decision becomes a geographical lobe. The fixed slots
// preserve spatial memory; the small title-derived offset stops every Room from
// producing the exact same silhouette without introducing random layout drift.
const ANCHOR_SLOTS = [
  [
    { x: 78, y: 78 }, { x: 146, y: 52 }, { x: 235, y: 82 },
    { x: 230, y: 145 }, { x: 157, y: 164 }, { x: 74, y: 139 },
  ],
  [
    { x: 91, y: 57 }, { x: 207, y: 61 }, { x: 245, y: 125 },
    { x: 177, y: 163 }, { x: 79, y: 144 }, { x: 66, y: 93 },
  ],
  [
    { x: 71, y: 99 }, { x: 123, y: 53 }, { x: 222, y: 60 },
    { x: 251, y: 125 }, { x: 183, y: 162 }, { x: 91, y: 150 },
  ],
  [
    { x: 82, y: 62 }, { x: 181, y: 48 }, { x: 245, y: 103 },
    { x: 218, y: 157 }, { x: 121, y: 164 }, { x: 67, y: 119 },
  ],
] as const;

function titleOffset(title: string, salt: number): number {
  let hash = 2166136261 ^ salt;
  for (const character of title) {
    hash ^= character.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 13) - 6;
}

function titleSeed(title: string): number {
  let seed = 0;
  for (const character of title) seed = Math.imul(seed ^ (character.codePointAt(0) ?? 0), 31);
  return Math.abs(seed);
}

function geometryToPath(geometry: ContourMultiPolygon | undefined): string {
  if (!geometry) return '';
  return geometry.coordinates
    .map((polygon) => polygon
      .map((ring) => {
        if (ring.length === 0) return '';
        const points = ring.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`);
        return `M${points.join('L')}Z`;
      })
      .join(''))
    .join('');
}

function createSemanticIslandGeometry(
  labels: readonly string[],
  seedLabel: string,
  shape: ProjectRoom['shape'],
): WayfinderIslandGeometry | null {
  if (labels.length < 2) return null;

  const slots = ANCHOR_SLOTS[shape - 1];
  const semanticAnchors = labels.slice(0, slots.length).map((title, index) => {
    const slot = slots[index];
    return {
      title,
      x: slot.x + titleOffset(`${seedLabel}:${title}`, index),
      y: slot.y + titleOffset(`${title}:${seedLabel}`, index + 31),
    };
  });

  const seed = titleSeed(seedLabel);
  const centerX = 156 + (seed % 11) - 5;
  const centerY = 106 + (Math.floor(seed / 11) % 9) - 4;

  const points: DensityPoint[] = [
    { x: centerX, y: centerY, weight: 2.7 },
    { x: centerX - 33, y: centerY + 8, weight: 1.9 },
    { x: centerX + 34, y: centerY + 5, weight: 1.9 },
    { x: centerX, y: centerY + 34, weight: 1.6 },
    ...semanticAnchors.flatMap((anchor) => [
      { x: anchor.x, y: anchor.y, weight: 1.55 },
      { x: anchor.x - 12, y: anchor.y + 6, weight: 1.05 },
      { x: anchor.x + 11, y: anchor.y + 10, weight: 1.05 },
    ]),
  ];

  const contours = contourDensity<DensityPoint>()
    .x((point) => point.x)
    .y((point) => point.y)
    .weight((point) => point.weight)
    .size([ISLAND_WIDTH, ISLAND_HEIGHT])
    .cellSize(2)
    .bandwidth(33)
    .thresholds(8)(points);

  if (contours.length < 5) return null;
  return {
    water: geometryToPath(contours[0]),
    shore: geometryToPath(contours[1]),
    highland: geometryToPath(contours[Math.min(3, contours.length - 1)]),
    contour: geometryToPath(contours[Math.min(4, contours.length - 1)]),
    semanticAnchors,
  };
}

export function createRoomIslandGeometry(
  room: Pick<ProjectRoom, 'areas' | 'id' | 'shape' | 'title'>,
): WayfinderIslandGeometry | null {
  const labels = room.areas.map((area) => area.title);
  return createSemanticIslandGeometry(labels, `${room.id}:${room.title}`, room.shape);
}

export function createWayfinderIslandGeometry(
  labels: readonly { title: string }[],
): WayfinderIslandGeometry | null {
  return createSemanticIslandGeometry(
    labels.map(({ title }) => title),
    labels.map(({ title }) => title).join('|'),
    1,
  );
}
