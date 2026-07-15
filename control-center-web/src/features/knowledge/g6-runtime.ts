// Keep the large graph runtime behind the route-level dynamic import in the
// canvas component. G6's public entry also performs the coordinated built-in
// registration that its element modules require.
export { Graph } from '@antv/g6';
