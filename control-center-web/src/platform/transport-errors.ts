import type { ControlPathId } from './routes';

/**
 * Typed HTTP failure shared by the HTTP adapter and public error projection.
 *
 * Keeping the receipt shape outside the concrete adapter lets native builds
 * classify persisted HTTP failures without bundling the HTTP transport itself.
 */
export class ControlTransportHttpError extends Error {
  readonly status: number;
  readonly pathId: ControlPathId;
  readonly payload: unknown;

  constructor(pathId: ControlPathId, status: number, message: string, payload?: unknown) {
    super(message);
    this.name = 'ControlTransportHttpError';
    this.pathId = pathId;
    this.status = status;
    this.payload = payload;
  }
}
