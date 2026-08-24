import type { HighlighterCore, LanguageInput, ShikiTransformer } from 'shiki/core';

type LanguageLoader = () => Promise<{ default: LanguageInput }>;

const LANGUAGE_LOADERS: Record<string, { id: string; load: LanguageLoader }> = {
  bash: { id: 'shellscript', load: () => import('shiki/dist/langs/shellscript.mjs') },
  c: { id: 'c', load: () => import('shiki/dist/langs/c.mjs') },
  cpp: { id: 'cpp', load: () => import('shiki/dist/langs/cpp.mjs') },
  csharp: { id: 'csharp', load: () => import('shiki/dist/langs/csharp.mjs') },
  css: { id: 'css', load: () => import('shiki/dist/langs/css.mjs') },
  go: { id: 'go', load: () => import('shiki/dist/langs/go.mjs') },
  html: { id: 'html', load: () => import('shiki/dist/langs/html.mjs') },
  java: { id: 'java', load: () => import('shiki/dist/langs/java.mjs') },
  javascript: { id: 'javascript', load: () => import('shiki/dist/langs/javascript.mjs') },
  json: { id: 'json', load: () => import('shiki/dist/langs/json.mjs') },
  jsx: { id: 'jsx', load: () => import('shiki/dist/langs/jsx.mjs') },
  kotlin: { id: 'kotlin', load: () => import('shiki/dist/langs/kotlin.mjs') },
  markdown: { id: 'markdown', load: () => import('shiki/dist/langs/markdown.mjs') },
  python: { id: 'python', load: () => import('shiki/dist/langs/python.mjs') },
  rust: { id: 'rust', load: () => import('shiki/dist/langs/rust.mjs') },
  shellscript: { id: 'shellscript', load: () => import('shiki/dist/langs/shellscript.mjs') },
  sql: { id: 'sql', load: () => import('shiki/dist/langs/sql.mjs') },
  swift: { id: 'swift', load: () => import('shiki/dist/langs/swift.mjs') },
  toml: { id: 'toml', load: () => import('shiki/dist/langs/toml.mjs') },
  tsx: { id: 'tsx', load: () => import('shiki/dist/langs/tsx.mjs') },
  typescript: { id: 'typescript', load: () => import('shiki/dist/langs/typescript.mjs') },
  vue: { id: 'vue', load: () => import('shiki/dist/langs/vue.mjs') },
  xml: { id: 'xml', load: () => import('shiki/dist/langs/xml.mjs') },
  yaml: { id: 'yaml', load: () => import('shiki/dist/langs/yaml.mjs') },
};

let highlighterPromise: Promise<HighlighterCore> | null = null;
const languageLoads = new Map<string, Promise<void>>();

export async function highlightCode(
  content: string,
  language: string,
  options: { inheritSurface?: boolean } = {},
): Promise<string> {
  const selection = LANGUAGE_LOADERS[normalizeLanguage(language)];
  if (!selection) return '';
  const highlighter = await highlighterInstance();
  let loading = languageLoads.get(selection.id);
  if (!loading) {
    loading = selection.load()
      .then(({ default: grammar }) => highlighter.loadLanguage(grammar));
    languageLoads.set(selection.id, loading);
  }
  await loading;
  return highlighter.codeToHtml(content, {
    lang: selection.id,
    theme: 'github-dark-default',
    transformers: options.inheritSurface ? [surfaceInheritTransformer] : [],
  });
}

/** Conversation code readers own their surface through the paired
 * `--color-code-bg`/`--color-code-text` tokens. Stripping shiki's inline root
 * colours keeps that single owner in charge while token spans keep their
 * escaped palette. */
const surfaceInheritTransformer: ShikiTransformer = {
  pre(node) {
    delete node.properties.style;
  },
};

async function highlighterInstance(): Promise<HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = Promise.all([
      import('shiki/core'),
      import('shiki/engine/javascript'),
      import('shiki/dist/themes/github-dark-default.mjs'),
    ]).then(([{ createHighlighterCore }, { createJavaScriptRegexEngine }, { default: theme }]) => (
      createHighlighterCore({
        engine: createJavaScriptRegexEngine(),
        langs: [],
        themes: [theme],
      })
    ));
  }
  return highlighterPromise;
}

function normalizeLanguage(value: string): string {
  const normalized = value.trim().toLowerCase();
  return ({
    cs: 'csharp',
    js: 'javascript',
    md: 'markdown',
    py: 'python',
    rs: 'rust',
    sh: 'shellscript',
    ts: 'typescript',
    yml: 'yaml',
  } as Record<string, string>)[normalized] ?? normalized;
}
