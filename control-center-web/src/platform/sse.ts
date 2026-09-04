export interface ParsedSseEvent {
  id: string;
  event: string;
  data: string;
  retry?: number;
}

export type ParsedSseFrameKind = 'comment' | 'event';

export class SseParser {
  private buffer = '';
  private eventId = '';
  private eventName = '';
  private dataLines: string[] = [];
  private retry: number | undefined;
  private commentSeen = false;

  constructor(
    private readonly onEvent: (event: ParsedSseEvent) => void,
    private readonly onFrame?: (kind: ParsedSseFrameKind) => void,
  ) {}

  push(chunk: string): void {
    this.buffer += chunk;
    let lineBreak = this.buffer.indexOf('\n');
    while (lineBreak >= 0) {
      const rawLine = this.buffer.slice(0, lineBreak);
      this.buffer = this.buffer.slice(lineBreak + 1);
      this.consumeLine(rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine);
      lineBreak = this.buffer.indexOf('\n');
    }
  }

  finish(): void {
    // SSE dispatch is committed by an empty line, not by transport EOF. A
    // connection can disappear after a syntactically valid prefix of an event;
    // emitting that prefix would advance Last-Event-ID and skip the complete
    // durable event on reconnect. Drop the unfinished frame and let replay
    // deliver it from the previous cursor.
    this.buffer = '';
    this.eventId = '';
    this.eventName = '';
    this.dataLines = [];
    this.retry = undefined;
    this.commentSeen = false;
  }

  private consumeLine(line: string): void {
    if (line.length === 0) {
      this.dispatch();
      return;
    }
    if (line.startsWith(':')) {
      this.commentSeen = true;
      return;
    }

    const separator = line.indexOf(':');
    const field = separator < 0 ? line : line.slice(0, separator);
    let value = separator < 0 ? '' : line.slice(separator + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    switch (field) {
      case 'data':
        this.dataLines.push(value);
        break;
      case 'event':
        this.eventName = value;
        break;
      case 'id':
        if (!value.includes('\u0000')) this.eventId = value;
        break;
      case 'retry': {
        const parsed = Number(value);
        if (Number.isInteger(parsed) && parsed >= 0) {
          this.retry = parsed;
        }
        break;
      }
      default:
        break;
    }
  }

  private dispatch(): void {
    const completedComment = this.commentSeen;
    if (this.dataLines.length === 0) {
      this.eventName = '';
      this.retry = undefined;
      this.commentSeen = false;
      if (completedComment) this.onFrame?.('comment');
      return;
    }
    this.onEvent({
      id: this.eventId,
      event: this.eventName || 'message',
      data: this.dataLines.join('\n'),
      ...(this.retry === undefined ? {} : { retry: this.retry }),
    });
    this.eventName = '';
    this.dataLines = [];
    this.retry = undefined;
    this.commentSeen = false;
    this.onFrame?.('event');
  }
}
