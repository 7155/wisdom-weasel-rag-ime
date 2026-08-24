import { describe, expect, it } from 'vitest';
import {
  browserActionLabel,
  browserElement,
  crashReasonText,
  formatBytes,
  historyDateTime,
  historyDayKey,
  historyDayLabel,
  hostTab,
  initialHostTab,
  isTextEntry,
  knownCount,
  normalizedAddress,
  omniboxIconKind,
  omniboxIconTitle,
  pageFailureText,
} from './paw-browser-model';

describe('PAW Browser guest model', () => {
  it('labels history days relative to a fixed now without inventing dates', () => {
    const now = new Date(2026, 7, 24, 15, 30).getTime();
    expect(historyDayKey(now)).toBe('2026-08-24');
    expect(historyDayLabel(new Date(2026, 7, 24, 1, 0).getTime(), now)).toBe('今天');
    expect(historyDayLabel(new Date(2026, 7, 23, 23, 59).getTime(), now)).toBe('昨天');
    const older = historyDayLabel(new Date(2026, 7, 20, 8, 0).getTime(), now);
    expect(older).toContain('8月20日');
    const lastYear = historyDayLabel(new Date(2025, 11, 31, 8, 0).getTime(), now);
    expect(lastYear).toContain('2025');
  });

  it('normalizes addresses into real navigations or one search', () => {
    expect(normalizedAddress('   ')).toBe('');
    expect(normalizedAddress('about:blank')).toBe('about:blank');
    expect(normalizedAddress('https://example.com/a?b=1')).toBe('https://example.com/a?b=1');
    expect(normalizedAddress('example.com/docs')).toBe('https://example.com/docs');
    expect(normalizedAddress('paw 浏览器')).toBe('https://www.google.com/search?q=paw%20%E6%B5%8F%E8%A7%88%E5%99%A8');
  });

  it('keeps the omnibox security icon truthful', () => {
    expect(omniboxIconKind('', '')).toBe('search');
    expect(omniboxIconKind('', 'about:blank')).toBe('search');
    expect(omniboxIconKind('https://a.example/', 'https://a.example/')).toBe('lock');
    expect(omniboxIconKind('http://a.example/', 'http://a.example/')).toBe('info');
    expect(omniboxIconKind('draft', 'https://a.example/')).toBe('search');
    expect(omniboxIconTitle('lock')).toBe('连接已加密');
    expect(omniboxIconTitle('info')).toBe('连接未加密');
    expect(omniboxIconTitle('search')).toBe('搜索或输入网址');
  });

  it('translates known, certificate, and unknown page failures', () => {
    expect(pageFailureText({ code: -105, description: '', url: 'https://x.example/' }))
      .toEqual({ title: '找不到这个网站', detail: '错误代码 -105' });
    expect(pageFailureText({ code: -201, description: 'ERR_CERT_DATE_INVALID', url: 'https://x.example/' }))
      .toEqual({ title: '网站证书无效或连接不安全', detail: 'ERR_CERT_DATE_INVALID' });
    expect(pageFailureText({ code: -999, description: '', url: 'https://x.example/' }))
      .toEqual({ title: '页面没有打开', detail: '错误代码 -999' });
  });

  it('names guest process exits and keeps unknown reasons safe', () => {
    expect(crashReasonText('crashed')).toBe('页面渲染进程崩溃');
    expect(crashReasonText('oom')).toBe('页面内存不足');
    expect(crashReasonText('mystery')).toBe('页面进程已退出');
  });

  it('labels Agent browser actions and falls back to the raw action', () => {
    expect(browserActionLabel('navigate')).toBe('打开页面');
    expect(browserActionLabel('take_over')).toBe('接管页面');
    expect(browserActionLabel('unknown_action')).toBe('unknown_action');
  });

  it('accepts only finite non-negative step counts', () => {
    expect(knownCount(undefined, 'x', -2, 5.9, 7)).toBe(5);
    expect(knownCount(undefined, null, Number.NaN)).toBeNull();
  });

  it('creates host tabs with readable initial titles', () => {
    expect(initialHostTab()).toEqual({ id: 'paw-tab-1', title: '新标签页', url: 'about:blank' });
    const opened = hostTab('https://example.com/', 'command-1');
    expect(opened.commandId).toBe('command-1');
    expect(opened.title).toBe('https://example.com/');
    expect(opened.id.startsWith('paw-tab-')).toBe(true);
    expect(hostTab('about:blank').title).toBe('新标签页');
  });

  it('keeps only hit targets with real geometry and recognizes text entries', () => {
    expect(browserElement({ refId: '', width: 10, height: 10 })).toBeNull();
    expect(browserElement({ refId: 'e1', width: 0, height: 10 })).toBeNull();
    const entry = browserElement({
      refId: 'e1', tag: 'input', role: 'textbox', label: '搜索', inputType: 'text', x: 1, y: 2, width: 10, height: 12,
    });
    expect(entry).toMatchObject({ refId: 'e1', tag: 'input', x: 1, y: 2, width: 10, height: 12 });
    expect(entry ? isTextEntry(entry) : null).toBe(true);
    const button = browserElement({ refId: 'e2', tag: 'button', role: 'button', width: 10, height: 10 });
    expect(button ? isTextEntry(button) : null).toBe(false);
  });

  it('formats history timestamps and byte counts', () => {
    expect(historyDateTime(0)).toBe('1970-01-01T00:00:00.000Z');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(4096)).toBe('4 KB');
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
  });
});
