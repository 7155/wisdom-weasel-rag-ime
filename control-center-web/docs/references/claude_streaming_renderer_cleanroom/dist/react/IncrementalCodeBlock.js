import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { memo, useMemo, useRef, } from "react";
import { IncrementalLineTokenizer, plainLineTokenizer, } from "../core/incrementalTokenizer.js";
function tokenStyle(token) {
    if (token.color === undefined && token.fontStyle === undefined)
        return undefined;
    const fontStyle = token.fontStyle ?? 0;
    return {
        color: token.color,
        fontStyle: fontStyle & 1 ? "italic" : undefined,
        fontWeight: fontStyle & 2 ? "bold" : undefined,
        textDecoration: fontStyle & 4 ? "underline" : undefined,
    };
}
function defaultRenderToken(token, key) {
    return (_jsx("span", { style: tokenStyle(token), children: token.content }, key));
}
const TokenLine = memo(function TokenLineInner(props) {
    const { line, lineNumber, showLineNumbers, renderToken } = props;
    return (_jsxs("span", { className: "pm-code-line", "data-line": lineNumber, children: [showLineNumbers ? (_jsx("span", { className: "pm-code-line-number", "aria-hidden": "true", children: lineNumber })) : null, _jsxs("span", { className: "pm-code-line-content", children: [line.tokens.map((token, index) => renderToken(token, `${line.startOffset}:${index}`)), line.separator] })] }));
}, (previous, next) => previous.line === next.line &&
    previous.lineNumber === next.lineNumber &&
    previous.showLineNumbers === next.showLineNumbers &&
    previous.renderToken === next.renderToken);
const PLAIN_TOKENIZER = plainLineTokenizer;
/**
 * Highlights only complete physical lines. The unfinished final line remains
 * plain while streaming, then receives one final tokenization after settle.
 */
export function IncrementalCodeBlock(props) {
    const { code, language, streaming, tokenizer, className, showLineNumbers = false, maxHighlightedChars = 204_800, renderToken = defaultRenderToken, } = props;
    const effectiveTokenizer = code.length <= maxHighlightedChars && tokenizer
        ? tokenizer
        : PLAIN_TOKENIZER;
    const engineRef = useRef(null);
    if (engineRef.current === null) {
        engineRef.current = new IncrementalLineTokenizer(effectiveTokenizer);
    }
    else {
        engineRef.current.setTokenizer(effectiveTokenizer);
    }
    const snapshot = useMemo(() => engineRef.current?.update(code, { streaming }), [code, streaming, effectiveTokenizer]);
    if (!snapshot)
        return null;
    const partialTokens = snapshot.partialTokens;
    const partialLineNumber = snapshot.completeLines.length + 1;
    return (_jsx("pre", { className: className, "data-language": language || undefined, children: _jsxs("code", { children: [snapshot.completeLines.map((line, index) => (_jsx(TokenLine, { line: line, lineNumber: index + 1, showLineNumbers: showLineNumbers, renderToken: renderToken }, line.startOffset))), snapshot.partialText.length > 0 || !streaming ? (_jsxs("span", { className: "pm-code-line", "data-line": partialLineNumber, children: [showLineNumbers ? (_jsx("span", { className: "pm-code-line-number", "aria-hidden": "true", children: partialLineNumber })) : null, _jsx("span", { className: "pm-code-line-content", children: partialTokens
                                ? partialTokens.map((token, index) => renderToken(token, `partial:${index}`))
                                : snapshot.partialText })] })) : null] }) }));
}
//# sourceMappingURL=IncrementalCodeBlock.js.map