import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useMemo, } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { IncrementalCodeBlock, } from "./IncrementalCodeBlock.js";
import { ProgressiveMarkdown, } from "./ProgressiveMarkdown.js";
/**
 * Ready-to-use adapter. It parses completed Markdown chunks independently
 * while streaming, and bypasses repeated Markdown parsing for a growing open
 * fenced code block.
 */
export function ReactMarkdownProgressive(props) {
    const { text, isStreaming, documentKey, className, holdBack, openFenceFastPath, showLineNumbers = false, renderVersion = 0, components, createTokenizer, onFirstPaint, onSettledCommit, } = props;
    const markdownComponents = useMemo(() => components, [components]);
    const renderChunk = useCallback((context) => {
        const { text: chunkText, openFence } = context;
        if (openFence) {
            const tokenizer = createTokenizer?.(openFence.language);
            return (_jsxs(_Fragment, { children: [openFence.prefix.trim().length > 0 ? (_jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], components: markdownComponents, children: openFence.prefix })) : null, _jsx(IncrementalCodeBlock, { code: openFence.value, language: openFence.language, streaming: true, tokenizer: tokenizer, showLineNumbers: showLineNumbers, className: openFence.language
                            ? `language-${openFence.language}`
                            : undefined })] }));
        }
        return (_jsx(ReactMarkdown, { remarkPlugins: [remarkGfm], components: markdownComponents, children: chunkText }));
    }, [createTokenizer, markdownComponents, showLineNumbers]);
    return (_jsx(ProgressiveMarkdown, { text: text, isStreaming: isStreaming, documentKey: documentKey, renderChunk: renderChunk, className: className, holdBack: holdBack, openFenceFastPath: openFenceFastPath, renderVersion: renderVersion, onFirstPaint: onFirstPaint, onSettledCommit: onSettledCommit }));
}
//# sourceMappingURL=ReactMarkdownAdapter.js.map