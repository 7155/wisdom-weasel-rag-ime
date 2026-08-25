/**
 * Shared composer-attachment policy for Session and Room dialogs.
 *
 * One place decides which pasted or picked files a composer accepts, so the
 * transports (http/native/preview), the Room event reducer, and the two
 * workspace wrappers cannot drift apart. Images keep their historical
 * PNG/JPEG/GIF/WebP set (they get thumbnails and inline rendering); every
 * other file rides the same managed-media receipt path as an opaque document.
 */

export const COMPOSER_IMAGE_MIME_TYPES = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
] as const;

export type ComposerImageMimeType = (typeof COMPOSER_IMAGE_MIME_TYPES)[number];

/** Managed-media import cap shared by every transport (20 MiB). */
export const MAX_COMPOSER_ATTACHMENT_BYTES = 20 * 1024 * 1024;

/** Per-message attachment cap shared by Session and Room composers. */
export const MAX_COMPOSER_ATTACHMENTS = 8;

const IMAGE_MIME_SET: ReadonlySet<string> = new Set(COMPOSER_IMAGE_MIME_TYPES);

// RFC 6838 token/token — enough structure to reject header-injection garbage
// without maintaining an allowlist of every document type users may paste.
const MIME_TYPE_PATTERN = /^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$/;

export function isComposerImageMimeType(value: string): value is ComposerImageMimeType {
  return IMAGE_MIME_SET.has(value.trim().toLowerCase());
}

/** Any syntactically valid MIME type is an acceptable composer attachment. */
export function isComposerAttachmentMimeType(value: string): boolean {
  return MIME_TYPE_PATTERN.test(value.trim().toLowerCase());
}

/**
 * Clipboard files frequently arrive without a type (code files, archives from
 * some file managers). They stay attachable: unknown or malformed types
 * normalize to application/octet-stream instead of being rejected.
 */
export function normalizeComposerAttachmentMimeType(value: string | undefined | null): string {
  const lower = (value ?? '').trim().toLowerCase();
  return MIME_TYPE_PATTERN.test(lower) ? lower : 'application/octet-stream';
}

/** Whether a chip should render an image thumbnail or a file-type badge. */
export function composerAttachmentKind(mimeType: string): 'image' | 'file' {
  return isComposerImageMimeType(mimeType) ? 'image' : 'file';
}

/**
 * Short uppercase type label for a non-image chip (`PDF`, `ZIP`, `TS`…).
 * Falls back from the file extension to the MIME subtype; empty when neither
 * yields something presentable, letting the chip show a generic icon.
 */
export function composerAttachmentBadge(fileName: string, mimeType: string): string {
  const extension = /\.([a-z0-9]{1,6})$/i.exec(fileName.trim())?.[1] ?? '';
  if (extension) return extension.toUpperCase();
  const subtype = normalizeComposerAttachmentMimeType(mimeType).split('/')[1] ?? '';
  if (!subtype || subtype === 'octet-stream') return '';
  const tail = subtype.split(/[.+-]/).filter(Boolean).at(-1) ?? '';
  return tail.length >= 2 && tail.length <= 6 ? tail.toUpperCase() : '';
}
