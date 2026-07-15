import { D3ForceLayout } from '@antv/layout';
import { AutoAdaptLabel } from '@antv/g6/esm/behaviors/auto-adapt-label.js';
import { DragCanvas } from '@antv/g6/esm/behaviors/drag-canvas.js';
import { DragElement } from '@antv/g6/esm/behaviors/drag-element.js';
import { HoverActivate } from '@antv/g6/esm/behaviors/hover-activate.js';
import { ZoomCanvas } from '@antv/g6/esm/behaviors/zoom-canvas.js';
import { Line } from '@antv/g6/esm/elements/edges/line.js';
import { Circle } from '@antv/g6/esm/elements/nodes/circle.js';
import { register } from '@antv/g6/esm/registry/register.js';
import { Graph } from '@antv/g6/esm/runtime/graph.js';
import { light } from '@antv/g6/esm/themes/light.js';

// G6's default entry registers every bundled layout, including Node-oriented
// CommonJS code. Register only the browser extensions this view actually uses
// so the native WebView bundle stays CSP-safe and substantially smaller.
register('node', 'circle', Circle);
register('edge', 'line', Line);
register('layout', 'd3-force', D3ForceLayout);
register('theme', 'light', light);
register('behavior', 'drag-canvas', DragCanvas);
register('behavior', 'drag-element', DragElement);
register('behavior', 'hover-activate', HoverActivate);
register('behavior', 'zoom-canvas', ZoomCanvas);
register('behavior', 'auto-adapt-label', AutoAdaptLabel);

export { Graph };
