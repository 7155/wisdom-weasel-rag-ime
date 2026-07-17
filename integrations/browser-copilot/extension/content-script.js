const MAX_INTERACTIVE = 320;
const MAX_TEXT_LINES = 220;
const MAX_MARKDOWN_CHARS = 120000;
let referenceMap = new Map();
let changeTimer = 0;

function compact(value, maximum = 500) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maximum);
}

function safeUrl(value) {
  try {
    const url = new URL(String(value || ''));
    url.username = '';
    url.password = '';
    url.hash = '';
    for (const key of [...url.searchParams.keys()]) {
      if (/(?:token|secret|password|passwd|auth|session|jwt|signature|api[_-]?key|code|state)/i.test(key)) {
        url.searchParams.set(key, '[redacted]');
      }
    }
    return url.href;
  } catch {
    return compact(value, 1000);
  }
}

function visible(element) {
  if (!(element instanceof Element)) return false;
  const style = getComputedStyle(element);
  if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function labelFor(element) {
  const aria = compact(element.getAttribute('aria-label'), 240);
  if (aria) return aria;
  const labelledBy = element.getAttribute('aria-labelledby');
  if (labelledBy) {
    const label = labelledBy
      .split(/\s+/)
      .map((id) => compact(document.getElementById(id)?.textContent, 160))
      .filter(Boolean)
      .join(' ');
    if (label) return label;
  }
  if (element.labels?.length) {
    const label = [...element.labels].map((item) => compact(item.textContent, 160)).filter(Boolean).join(' ');
    if (label) return label;
  }
  return (
    compact(element.getAttribute('placeholder'), 240)
    || compact(element.getAttribute('title'), 240)
    || compact(element.innerText || element.textContent, 240)
    || compact(element.getAttribute('name'), 120)
  );
}

function roleFor(element) {
  const explicit = compact(element.getAttribute('role'), 40);
  if (explicit) return explicit;
  const tag = element.tagName.toLowerCase();
  if (tag === 'a') return 'link';
  if (tag === 'button') return 'button';
  if (tag === 'select') return 'combobox';
  if (tag === 'textarea') return 'textbox';
  if (tag === 'input') {
    const type = String(element.type || 'text').toLowerCase();
    if (type === 'checkbox') return 'checkbox';
    if (type === 'radio') return 'radio';
    if (type === 'submit' || type === 'button') return 'button';
    return 'textbox';
  }
  return tag;
}

function interactiveElements() {
  const selector = [
    'a[href]',
    'button',
    'input:not([type="hidden"])',
    'textarea',
    'select',
    '[role="button"]',
    '[role="link"]',
    '[role="textbox"]',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return [...document.querySelectorAll(selector)].filter(visible).slice(0, MAX_INTERACTIVE);
}

function buildSnapshot() {
  referenceMap = new Map();
  const interactive = interactiveElements();
  const interactiveLines = interactive.map((element, index) => {
    const refId = `e${index + 1}`;
    referenceMap.set(refId, element);
    const role = roleFor(element);
    const label = labelFor(element) || '未命名';
    const states = [];
    if (element.disabled) states.push('disabled');
    if (element.checked) states.push('checked');
    if (element.getAttribute('aria-expanded')) states.push(`expanded=${element.getAttribute('aria-expanded')}`);
    if (element.tagName === 'A') states.push(`href=${compact(safeUrl(element.href), 500)}`);
    if (element.tagName === 'INPUT' && String(element.type).toLowerCase() === 'password') states.push('sensitive');
    return `- [${refId}] ${role} "${label.replaceAll('"', '\\"')}"${states.length ? ` (${states.join(', ')})` : ''}`;
  });

  const textLines = [];
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
  while (walker.nextNode() && textLines.length < MAX_TEXT_LINES) {
    const element = walker.currentNode;
    if (!visible(element)) continue;
    const tag = element.tagName.toLowerCase();
    if (!['h1', 'h2', 'h3', 'h4', 'p', 'li', 'blockquote', 'figcaption', 'pre', 'code'].includes(tag)) continue;
    if (element.closest('script,style,noscript,svg')) continue;
    const text = compact(element.innerText || element.textContent, 1000);
    if (!text || textLines.at(-1)?.endsWith(text)) continue;
    const prefix = tag.startsWith('h') ? `${'#'.repeat(Number(tag[1]))} ` : tag === 'li' ? '- ' : '';
    textLines.push(`${prefix}${text}`);
  }

  const images = [...document.images]
    .filter(visible)
    .slice(0, 30)
    .map((image) => {
      const alt = compact(image.alt || image.getAttribute('aria-label') || image.title, 160) || '页面图片';
      const src = compact(safeUrl(image.currentSrc || image.src), 1000);
      return src && !src.startsWith('data:') ? `![${alt.replaceAll(']', '\\]')}](${src})` : `- 图片：${alt}`;
    });

  const markdown = [
    `# ${compact(document.title, 500) || '未命名页面'}`,
    `URL: ${safeUrl(location.href)}`,
    '',
    '## 可交互元素',
    ...(interactiveLines.length ? interactiveLines : ['- 当前视口没有可交互元素']),
    '',
    ...(images.length ? ['## 图片', ...images, ''] : []),
    '## 页面正文',
    ...(textLines.length ? textLines : ['当前页面没有可读取正文。']),
  ].join('\n').slice(0, MAX_MARKDOWN_CHARS);

  return {
    snapshotId: `snap_${crypto.randomUUID().replaceAll('-', '')}`,
    url: location.href,
    title: compact(document.title, 500),
    summary: `${interactive.length} 个可交互元素 · ${textLines.length} 段正文 · ${images.length} 张图片`,
    markdown,
    interactiveCount: interactive.length,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      scrollX: Math.round(window.scrollX),
      scrollY: Math.round(window.scrollY),
      documentWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
    },
  };
}

function targetFor(refId) {
  const element = referenceMap.get(refId);
  return element?.isConnected ? element : undefined;
}

function setNativeValue(element, value) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  if (setter) setter.call(element, value);
  else element.value = value;
}

async function runCommand(message) {
  const action = message.action;
  if (action === 'snapshot' || action === 'read_page') return { ok: true, ...buildSnapshot() };
  if (action === 'click') {
    const target = targetFor(message.refId);
    if (!target) throw new Error(`页面引用已失效: ${message.refId}`);
    target.scrollIntoView({ block: 'center', inline: 'center' });
    target.click();
    return { ok: true, summary: `已点击 ${labelFor(target) || message.refId}` };
  }
  if (action === 'type') {
    const target = targetFor(message.refId);
    if (!target) throw new Error(`页面引用已失效: ${message.refId}`);
    if (target instanceof HTMLInputElement && String(target.type).toLowerCase() === 'password') {
      throw new Error('出于安全原因，Agent 不能向密码字段输入内容');
    }
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable)) {
      throw new Error('目标元素不是可编辑字段');
    }
    target.focus();
    if (target.isContentEditable) {
      if (message.clear !== false) target.textContent = '';
      target.textContent += String(message.text || '');
    } else {
      const next = message.clear === false ? `${target.value}${message.text || ''}` : String(message.text || '');
      setNativeValue(target, next);
    }
    target.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: String(message.text || '') }));
    target.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, summary: `已向 ${labelFor(target) || message.refId} 输入 ${String(message.text || '').length} 个字符` };
  }
  if (action === 'scroll') {
    const amount = Number(message.amount || 650);
    const dx = message.direction === 'left' ? -amount : message.direction === 'right' ? amount : 0;
    const dy = message.direction === 'up' ? -amount : message.direction === 'down' ? amount : 0;
    window.scrollBy({ left: dx, top: dy, behavior: 'smooth' });
    return { ok: true, summary: `页面已向${message.direction || 'down'}滚动` };
  }
  if (action === 'wait') {
    const expected = String(message.text || '');
    const deadline = Date.now() + Math.min(Math.max(Number(message.timeoutMs || 5000), 100), 20000);
    while (Date.now() < deadline) {
      if (!expected || document.body?.innerText.includes(expected)) {
        return { ok: true, summary: expected ? `页面已出现“${compact(expected, 120)}”` : '页面等待完成' };
      }
      await new Promise((resolve) => setTimeout(resolve, 120));
    }
    throw new Error(`等待页面文本超时: ${compact(expected, 120)}`);
  }
  throw new Error(`不支持的页面操作: ${action}`);
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== 'browser.command') return undefined;
  runCommand(message)
    .then((result) => sendResponse(result))
    .catch((error) => sendResponse({ ok: false, error: String(error?.message || error), failureReason: 'page_command_failed' }));
  return true;
});

const observer = new MutationObserver(() => {
  clearTimeout(changeTimer);
  changeTimer = setTimeout(() => {
    chrome.runtime.sendMessage({ type: 'browser.pageChanged' }).catch(() => undefined);
  }, 700);
});

observer.observe(document.documentElement, {
  attributes: true,
  childList: true,
  subtree: true,
  characterData: true,
});

chrome.runtime.sendMessage({ type: 'browser.pageChanged' }).catch(() => undefined);
