/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/pi-runtime-manifest.v1.json
 */

export interface PiRuntimeManifestV1 {
  schemaVersion: 'rag-ime.pi-runtime-manifest.v1';
  runtimeVersion: string;
  piVersion: string;
  runtimeProtocolVersion?: '1' | '2';
  platform: string;
  architecture: string;
  launchKind: 'node' | 'standalone';
  piEntrypoint: string;
  nodeEntrypoint?: string;
  extensionEntrypoint: string;
  tools: string[];
  createdAtMs: number;
  source: {
    repository: string;
    commit: string;
    package: string;
    [k: string]: unknown;
  };
  files: {
    path: string;
    sha256: string;
    byteSize: number;
    executable: boolean;
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
