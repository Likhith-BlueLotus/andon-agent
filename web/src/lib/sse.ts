/**
 * Incremental Server-Sent Events parser. Pure: feed it decoded text chunks of any size and it
 * returns the frames completed so far. Handles chunk boundaries inside a line or a frame,
 * CRLF / LF / CR line endings, multi-line `data:`, `id:` / `event:` fields and `: ping` comments.
 */
export interface SseFrame {
  event: string; // "message" when the frame carries no `event:` field
  data: string; // multi-line data joined with "\n"
  id: string | null;
}

export interface SseResult {
  frames: SseFrame[];
  /** Number of comment lines (e.g. `: ping` heartbeats) seen in this push. */
  comments: number;
}

export class SseParser {
  private buf = "";
  private skipLf = false; // previous chunk ended in "\r"; swallow a leading "\n"
  private event = "";
  private data: string[] = [];
  private id: string | null = null;
  private hasFields = false;

  push(chunk: string): SseResult {
    const out: SseResult = { frames: [], comments: 0 };
    if (this.skipLf && chunk.startsWith("\n")) chunk = chunk.slice(1);
    this.skipLf = chunk.endsWith("\r");
    this.buf += chunk;
    // Normalise line endings; keep a trailing partial line in the buffer.
    const lines = this.buf.split(/\r\n|\r|\n/);
    this.buf = lines.pop() ?? "";
    // A lone trailing "\r" leaves buf === "" and is fine: the next "\n" is skipped via skipLf.
    for (const line of lines) this.line(line, out);
    return out;
  }

  /** Flush at end of stream: a final unterminated frame is discarded (per the SSE spec). */
  reset(): void {
    this.buf = "";
    this.event = "";
    this.data = [];
    this.id = null;
    this.hasFields = false;
    this.skipLf = false;
  }

  private line(line: string, out: SseResult): void {
    if (line === "") {
      if (this.hasFields) {
        out.frames.push({ event: this.event || "message", data: this.data.join("\n"), id: this.id });
      }
      this.event = "";
      this.data = [];
      this.id = null;
      this.hasFields = false;
      return;
    }
    if (line.startsWith(":")) {
      out.comments += 1;
      return;
    }
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    let value = i === -1 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        this.event = value;
        this.hasFields = true;
        break;
      case "data":
        this.data.push(value);
        this.hasFields = true;
        break;
      case "id":
        this.id = value;
        this.hasFields = true;
        break;
      default:
        break; // retry: and unknown fields are ignored
    }
  }
}

/** Convenience for tests and one-shot parsing. */
export function parseSse(text: string): SseResult {
  return new SseParser().push(text + (text.endsWith("\n") ? "" : "\n\n"));
}
