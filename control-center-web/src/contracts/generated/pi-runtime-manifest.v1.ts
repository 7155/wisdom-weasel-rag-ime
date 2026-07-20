/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/pi-runtime-manifest.v1.json
 */

export type PiRuntimeManifestV1 = {
  [k: string]: unknown;
} & {
  schemaVersion: 'rag-ime.pi-runtime-manifest.v1';
  runtimeVersion: string;
  piVersion: string;
  runtimeProtocolVersion?: '1' | '2';
  runtimeMethods?: string[];
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
    sourceContractSha256?: string;
    handlersCommit?: string;
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
};
