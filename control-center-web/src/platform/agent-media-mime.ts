/**
 * Managed Agent media MIME truth, mirrored from the owning Runtime store
 * (`rag_ime/agent_media.py`: ALLOWED_MEDIA_MIME_TYPES and _MAX_BYTES_BY_MIME).
 *
 * `/api/agent/media/import` accepts exactly these types for both Session-owned
 * and Room-owned attachments. Room *messages* additionally restrict their
 * attachment receipts to images (room-post.v2 + agent_service
 * `_resolve_room_attachments`), so Room surfaces must reject non-image files
 * before import instead of faking an upload that the message would refuse.
 */

const MEBIBYTE = 1024 * 1024;

export const AGENT_MEDIA_MAX_BYTES_BY_MIME: Readonly<Record<string, number>> = {
  'image/png': 20 * MEBIBYTE,
  'image/jpeg': 20 * MEBIBYTE,
  'image/gif': 20 * MEBIBYTE,
  'image/webp': 20 * MEBIBYTE,
  'audio/mpeg': 100 * MEBIBYTE,
  'audio/mp4': 100 * MEBIBYTE,
  'audio/wav': 100 * MEBIBYTE,
  'application/pdf': 25 * MEBIBYTE,
  'text/plain': 2 * MEBIBYTE,
  'text/markdown': 2 * MEBIBYTE,
  'text/html': 2 * MEBIBYTE,
  'text/x-diff': 2 * MEBIBYTE,
  'text/x-patch': 2 * MEBIBYTE,
};

export const AGENT_MEDIA_MIME_TYPES: ReadonlySet<string> = new Set(
  Object.keys(AGENT_MEDIA_MAX_BYTES_BY_MIME),
);

export const AGENT_IMAGE_MIME_TYPES: ReadonlySet<string> = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
]);

/** Room message attachments stay image-only until the Runtime widens room-post.v2. */
export const ROOM_ATTACHMENT_MIME_TYPES: ReadonlySet<string> = AGENT_IMAGE_MIME_TYPES;

/** Human copy for truthful unsupported-attachment errors. */
export const AGENT_MEDIA_KINDS_TEXT = '图片（PNG/JPEG/GIF/WebP）、PDF、音频（MP3/M4A/WAV）与文本（TXT/MD/HTML/DIFF/PATCH）';
export const ROOM_ATTACHMENT_KINDS_TEXT = 'PNG、JPEG、GIF 或 WebP 图片';

const EXTENSION_MIME_TYPES: Readonly<Record<string, string>> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  mp3: 'audio/mpeg',
  m4a: 'audio/mp4',
  mp4: 'audio/mp4',
  wav: 'audio/wav',
  pdf: 'application/pdf',
  txt: 'text/plain',
  log: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
  html: 'text/html',
  htm: 'text/html',
  diff: 'text/x-diff',
  patch: 'text/x-patch',
};

/**
 * Browsers leave `File.type` empty (or a generic octet-stream) for many text
 * formats a person actually pastes — `.md`, `.log`, `.patch`. Recover the
 * Runtime-accepted type from the extension instead of refusing the paste.
 * A concrete declared type is never overridden.
 */
export function agentMediaMimeForFile(file: { name: string; type: string }): string {
  const declared = String(file.type || '').trim().toLowerCase();
  if (declared && declared !== 'application/octet-stream') return declared;
  const extension = file.name.toLowerCase().split('.').at(-1) ?? '';
  return EXTENSION_MIME_TYPES[extension] ?? declared;
}

/** Re-type a File whose extension names a supported MIME the browser omitted. */
export function normalizeAgentMediaFile(file: File): File {
  const mimeType = agentMediaMimeForFile(file);
  const declared = String(file.type || '').toLowerCase();
  if (!mimeType || mimeType === declared || !AGENT_MEDIA_MIME_TYPES.has(mimeType)) return file;
  return new File([file], file.name, { type: mimeType, lastModified: file.lastModified });
}

/** Byte cap for one supported MIME type; 0 for anything the Runtime refuses. */
export function agentMediaMaxBytes(mimeType: string): number {
  return AGENT_MEDIA_MAX_BYTES_BY_MIME[String(mimeType || '').toLowerCase()] ?? 0;
}

export interface AttachmentFileSplit {
  accepted: File[];
  /** Truthfully unsupported for the given allowlist — never uploaded. */
  rejected: File[];
  /** Supported type but larger than the Runtime's byte cap for that type. */
  oversized: File[];
}

/** Partition pasted/dropped files against an owner-specific allowlist. */
export function splitAttachmentFiles(
  files: readonly File[],
  allowed: ReadonlySet<string> = AGENT_MEDIA_MIME_TYPES,
): AttachmentFileSplit {
  const split: AttachmentFileSplit = { accepted: [], rejected: [], oversized: [] };
  for (const file of files) {
    const normalized = normalizeAgentMediaFile(file);
    const mimeType = normalized.type.toLowerCase();
    if (!allowed.has(mimeType) || !AGENT_MEDIA_MIME_TYPES.has(mimeType)) {
      split.rejected.push(normalized);
    } else if (normalized.size <= 0 || normalized.size > agentMediaMaxBytes(mimeType)) {
      split.oversized.push(normalized);
    } else {
      split.accepted.push(normalized);
    }
  }
  return split;
}

export function attachmentFileLabel(file: { name: string; type: string }): string {
  return file.name || file.type || '未知文件';
}

/** Truthful skip report for one paste/pick batch; '' when nothing was skipped. */
export function attachmentSplitErrorText(split: AttachmentFileSplit, kindsText: string): string {
  const parts: string[] = [];
  if (split.rejected.length) {
    parts.push(`这里只支持${kindsText}，已跳过：${split.rejected.map(attachmentFileLabel).join('、')}`);
  }
  if (split.oversized.length) {
    parts.push(`超出大小限制，已跳过：${split.oversized.map(attachmentFileLabel).join('、')}`);
  }
  return parts.length ? `${parts.join('；')}。` : '';
}

/** `accept` attribute for a DOM file picker bound to an owner allowlist. */
export function agentMediaPickAccept(
  allowed: ReadonlySet<string> = AGENT_MEDIA_MIME_TYPES,
): string {
  return [...allowed].join(',');
}

/**
 * Browser file pick fallback for transports without a native picker: the
 * chosen Files feed the same managed `pasteImages` import path the clipboard
 * uses, so the receipt contract stays identical.
 */
export function pickBrowserAttachmentFiles(options: {
  accept: string;
  multiple?: boolean;
}): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = options.accept;
    input.multiple = options.multiple ?? true;
    input.style.display = 'none';
    const finish = (): void => {
      input.remove();
      resolve([...(input.files ?? [])]);
    };
    input.addEventListener('change', finish, { once: true });
    input.addEventListener('cancel', finish, { once: true });
    document.body.append(input);
    input.click();
  });
}
