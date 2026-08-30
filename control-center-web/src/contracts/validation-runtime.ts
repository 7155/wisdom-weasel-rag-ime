export type ContractValidationRuntime = typeof import('./validators');

let runtimePromise: Promise<ContractValidationRuntime> | null = null;

/**
 * The generated AJV bundle is intentionally loaded only when a route actually
 * needs contract validation or a validated Runtime stream is opened. Keeping
 * this promise here preserves one shared module instance without putting all
 * generated validators on the product shell's startup path.
 */
export function loadContractValidationRuntime(): Promise<ContractValidationRuntime> {
  runtimePromise ??= import('./validators');
  return runtimePromise;
}
