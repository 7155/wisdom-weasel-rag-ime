import { describe, expect, it } from 'vitest';
import { extractMarkdownOutline, plainHeadingText } from './reading-outline';

function numbered(lines: readonly string[], startAt = 1) {
  return lines.map((content, index) => ({ lineNumber: startAt + index, content }));
}

describe('knowledge reading outline', () => {
  it('collects ATX headings with their level and source line', () => {
    const outline = extractMarkdownOutline(numbered([
      '# 总览',
      '正文',
      '## 安装 ##',
      '###### 深层',
      '####### 不是标题',
      '#没有空格不是标题',
    ]));
    expect(outline).toEqual([
      { id: 'knowledge-heading-1', index: 0, level: 1, text: '总览', lineNumber: 1 },
      { id: 'knowledge-heading-3', index: 1, level: 2, text: '安装', lineNumber: 3 },
      { id: 'knowledge-heading-4', index: 2, level: 6, text: '深层', lineNumber: 4 },
    ]);
  });

  it('ignores headings inside fenced code blocks', () => {
    const outline = extractMarkdownOutline(numbered([
      '# 真标题',
      '```md',
      '# 代码里的假标题',
      '```',
      '~~~',
      '## 也是代码',
      '~~~',
      '## 尾部标题',
    ]));
    expect(outline.map((item) => item.text)).toEqual(['真标题', '尾部标题']);
  });

  it('recognises setext headings but not thematic breaks or list items', () => {
    const outline = extractMarkdownOutline(numbered([
      '一级标题',
      '===',
      '二级标题',
      '---',
      '',
      '---',
      '- 列表项',
      '---',
      '> 引用',
      '---',
    ]));
    expect(outline).toEqual([
      { id: 'knowledge-heading-1', index: 0, level: 1, text: '一级标题', lineNumber: 1 },
      { id: 'knowledge-heading-3', index: 1, level: 2, text: '二级标题', lineNumber: 3 },
    ]);
  });

  it('skips empty headings and keeps duplicate texts as separate entries', () => {
    const outline = extractMarkdownOutline(numbered(['#', '## 重复', '正文', '## 重复']));
    expect(outline.map((item) => [item.text, item.lineNumber])).toEqual([['重复', 2], ['重复', 4]]);
  });

  it('strips inline markup the way the DOM renders heading text', () => {
    expect(plainHeadingText('**加粗** 与 `代码` 和 [链接](https://example.test)')).toBe('加粗 与 代码 和 链接');
    expect(plainHeadingText('![图](x.png) *斜体* ~~删除~~  多  空格')).toBe('图 斜体 删除 多 空格');
    expect(plainHeadingText('   ')).toBe('');
  });
});
