import {
  memo,
  useMemo,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  IncrementalLineTokenizer,
  plainLineTokenizer,
  type CachedTokenLine,
  type StatefulLineTokenizer,
} from "../core/incrementalTokenizer.js";

export interface DisplayToken {
  readonly content: string;
  readonly color?: string;
  readonly fontStyle?: number;
}

export interface IncrementalCodeBlockProps<TState = unknown> {
  readonly code: string;
  readonly language?: string | undefined;
  readonly streaming: boolean;
  readonly tokenizer?: StatefulLineTokenizer<DisplayToken, TState> | undefined;
  readonly className?: string | undefined;
  readonly showLineNumbers?: boolean | undefined;
  readonly maxHighlightedChars?: number | undefined;
  readonly renderToken?:
    | ((token: DisplayToken, key: string) => ReactNode)
    | undefined;
}

function tokenStyle(token: DisplayToken): CSSProperties | undefined {
  if (token.color === undefined && token.fontStyle === undefined) return undefined;
  const fontStyle = token.fontStyle ?? 0;
  return {
    color: token.color,
    fontStyle: fontStyle & 1 ? "italic" : undefined,
    fontWeight: fontStyle & 2 ? "bold" : undefined,
    textDecoration: fontStyle & 4 ? "underline" : undefined,
  };
}

function defaultRenderToken(token: DisplayToken, key: string): ReactNode {
  return (
    <span key={key} style={tokenStyle(token)}>
      {token.content}
    </span>
  );
}

interface TokenLineProps {
  readonly line: CachedTokenLine<DisplayToken, unknown>;
  readonly lineNumber: number;
  readonly showLineNumbers: boolean;
  readonly renderToken: (token: DisplayToken, key: string) => ReactNode;
}

const TokenLine = memo(
  function TokenLineInner(props: TokenLineProps): ReactNode {
    const { line, lineNumber, showLineNumbers, renderToken } = props;
    return (
      <span className="pm-code-line" data-line={lineNumber}>
        {showLineNumbers ? (
          <span className="pm-code-line-number" aria-hidden="true">
            {lineNumber}
          </span>
        ) : null}
        <span className="pm-code-line-content">
          {line.tokens.map((token, index) =>
            renderToken(token, `${line.startOffset}:${index}`),
          )}
          {line.separator}
        </span>
      </span>
    );
  },
  (previous, next) =>
    previous.line === next.line &&
    previous.lineNumber === next.lineNumber &&
    previous.showLineNumbers === next.showLineNumbers &&
    previous.renderToken === next.renderToken,
);

const PLAIN_TOKENIZER = plainLineTokenizer as unknown as StatefulLineTokenizer<
  DisplayToken,
  unknown
>;

/**
 * Highlights only complete physical lines. The unfinished final line remains
 * plain while streaming, then receives one final tokenization after settle.
 */
export function IncrementalCodeBlock<TState = unknown>(
  props: IncrementalCodeBlockProps<TState>,
): ReactNode {
  const {
    code,
    language,
    streaming,
    tokenizer,
    className,
    showLineNumbers = false,
    maxHighlightedChars = 204_800,
    renderToken = defaultRenderToken,
  } = props;

  const effectiveTokenizer =
    code.length <= maxHighlightedChars && tokenizer
      ? tokenizer
      : (PLAIN_TOKENIZER as StatefulLineTokenizer<DisplayToken, TState>);

  const engineRef = useRef<IncrementalLineTokenizer<DisplayToken, TState> | null>(
    null,
  );
  if (engineRef.current === null) {
    engineRef.current = new IncrementalLineTokenizer(effectiveTokenizer);
  } else {
    engineRef.current.setTokenizer(effectiveTokenizer);
  }

  const snapshot = useMemo(
    () => engineRef.current?.update(code, { streaming }),
    [code, streaming, effectiveTokenizer],
  );
  if (!snapshot) return null;

  const partialTokens = snapshot.partialTokens;
  const partialLineNumber = snapshot.completeLines.length + 1;
  return (
    <pre className={className} data-language={language || undefined}>
      <code>
        {snapshot.completeLines.map((line, index) => (
          <TokenLine
            key={line.startOffset}
            line={line}
            lineNumber={index + 1}
            showLineNumbers={showLineNumbers}
            renderToken={renderToken}
          />
        ))}
        {snapshot.partialText.length > 0 || !streaming ? (
          <span className="pm-code-line" data-line={partialLineNumber}>
            {showLineNumbers ? (
              <span className="pm-code-line-number" aria-hidden="true">
                {partialLineNumber}
              </span>
            ) : null}
            <span className="pm-code-line-content">
              {partialTokens
                ? partialTokens.map((token, index) =>
                    renderToken(token, `partial:${index}`),
                  )
                : snapshot.partialText}
            </span>
          </span>
        ) : null}
      </code>
    </pre>
  );
}
