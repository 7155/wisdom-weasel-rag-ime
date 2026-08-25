import { describe, expect, it } from 'vitest';

import {
  COMPOSER_IMAGE_MIME_TYPES,
  MAX_COMPOSER_ATTACHMENTS,
  MAX_COMPOSER_ATTACHMENT_BYTES,
  composerAttachmentBadge,
  composerAttachmentKind,
  isComposerAttachmentMimeType,
  isComposerImageMimeType,
  normalizeComposerAttachmentMimeType,
} from './attachment-policy';

describe('attachment policy', () => {
  it('keeps the historical image set as images', () => {
    for (const mimeType of COMPOSER_IMAGE_MIME_TYPES) {
      expect(isComposerImageMimeType(mimeType)).toBe(true);
      expect(composerAttachmentKind(mimeType)).toBe('image');
    }
    expect(isComposerImageMimeType('IMAGE/PNG')).toBe(true);
    expect(isComposerImageMimeType('image/svg+xml')).toBe(false);
  });

  it('accepts non-image document types as attachments', () => {
    for (const mimeType of [
      'application/pdf',
      'text/plain',
      'text/markdown',
      'application/zip',
      'application/json',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'image/svg+xml',
      'application/octet-stream',
    ]) {
      expect(isComposerAttachmentMimeType(mimeType)).toBe(true);
    }
    expect(composerAttachmentKind('application/pdf')).toBe('file');
  });

  it('rejects malformed MIME strings instead of forwarding them to transports', () => {
    for (const mimeType of ['', 'pdf', 'application/', '/zip', 'a b/c', 'text/plain; charset=utf-8', 'text\n/plain']) {
      expect(isComposerAttachmentMimeType(mimeType)).toBe(false);
    }
  });

  it('normalizes missing or malformed types to octet-stream', () => {
    expect(normalizeComposerAttachmentMimeType('')).toBe('application/octet-stream');
    expect(normalizeComposerAttachmentMimeType(undefined)).toBe('application/octet-stream');
    expect(normalizeComposerAttachmentMimeType('Text/Plain')).toBe('text/plain');
    expect(normalizeComposerAttachmentMimeType('text/plain; charset=utf-8')).toBe('application/octet-stream');
  });

  it('derives a compact badge from extension first, then subtype', () => {
    expect(composerAttachmentBadge('report.pdf', 'application/pdf')).toBe('PDF');
    expect(composerAttachmentBadge('archive.tar.gz', 'application/gzip')).toBe('GZ');
    expect(composerAttachmentBadge('noext', 'application/zip')).toBe('ZIP');
    expect(composerAttachmentBadge('noext', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')).toBe('');
    expect(composerAttachmentBadge('noext', '')).toBe('');
  });

  it('keeps the shared byte and count caps stable', () => {
    expect(MAX_COMPOSER_ATTACHMENT_BYTES).toBe(20 * 1024 * 1024);
    expect(MAX_COMPOSER_ATTACHMENTS).toBe(8);
  });
});
