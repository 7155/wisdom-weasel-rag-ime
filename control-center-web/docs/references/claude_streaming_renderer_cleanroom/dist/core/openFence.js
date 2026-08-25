function isClosingFence(line, marker, minimumLength) {
    let index = 0;
    while (index < 3 && line.charCodeAt(index) === 32)
        index += 1;
    let count = 0;
    while (line[index] === marker) {
        index += 1;
        count += 1;
    }
    if (count < minimumLength)
        return false;
    for (; index < line.length; index += 1) {
        const code = line.charCodeAt(index);
        if (code !== 9 && code !== 32)
            return false;
    }
    return true;
}
/**
 * Detect a top-level fenced code block that is still open at the end of a
 * streaming Markdown tail. The conservative exclusions avoid front matter,
 * CR/NUL normalization ambiguity, and nested constructs that need a full
 * parser.
 */
export function detectOpenFenceTail(text) {
    if (text.includes("\r") ||
        text.includes("\0") ||
        text.startsWith("---") ||
        text.startsWith("+++")) {
        return null;
    }
    let open;
    let lineStart = 0;
    let lineNumber = 1;
    let finalLineStart = 0;
    let finalLineNumber = 1;
    while (lineStart <= text.length) {
        let lineEnd = text.indexOf("\n", lineStart);
        if (lineEnd < 0)
            lineEnd = text.length;
        finalLineStart = lineStart;
        finalLineNumber = lineNumber;
        const line = text.slice(lineStart, lineEnd);
        if (!open) {
            const match = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
            const run = match?.[1];
            if (run) {
                const marker = run[0];
                const info = match?.[2] ?? "";
                // CommonMark forbids backticks in the info string of a backtick fence.
                if (marker !== "`" || !info.includes("`")) {
                    open = {
                        marker,
                        length: run.length,
                        lineStart,
                        lineEnd,
                        info: info.trim(),
                    };
                }
            }
        }
        else if (isClosingFence(line, open.marker, open.length)) {
            open = undefined;
        }
        if (lineEnd === text.length)
            break;
        lineStart = lineEnd + 1;
        lineNumber += 1;
    }
    if (!open)
        return null;
    const valueStart = Math.min(open.lineEnd + 1, text.length);
    let value = text.slice(valueStart);
    if (value.endsWith("\n"))
        value = value.slice(0, -1);
    const language = open.info.split(/\s+/, 1)[0] ?? "";
    return {
        marker: open.marker,
        markerLength: open.length,
        openingLineStart: open.lineStart,
        openingLineEnd: open.lineEnd,
        prefix: text.slice(0, open.lineStart),
        parseHead: text.slice(0, open.lineEnd),
        info: open.info,
        language,
        value,
        end: {
            line: finalLineNumber,
            column: text.length - finalLineStart + 1,
            offset: text.length,
        },
    };
}
//# sourceMappingURL=openFence.js.map