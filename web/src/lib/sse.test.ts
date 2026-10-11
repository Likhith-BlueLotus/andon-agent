import { describe, expect, it } from "vitest";
import { SseParser, parseSse } from "./sse";

describe("SseParser", () => {
  it("parses a complete frame", () => {
    const r = new SseParser().push('id: 3\nevent: plan\ndata: {"a":1}\n\n');
    expect(r.frames).toEqual([{ event: "plan", data: '{"a":1}', id: "3" }]);
  });

  it("handles chunk boundaries anywhere, even mid-field", () => {
    const text = 'id: 1\nevent: tool_call\ndata: {"x":"y"}\n\nid: 2\nevent: done\ndata: {}\n\n';
    for (let cut = 1; cut < text.length; cut++) {
      const p = new SseParser();
      const frames = [...p.push(text.slice(0, cut)).frames, ...p.push(text.slice(cut)).frames];
      expect(frames.map((f) => f.event)).toEqual(["tool_call", "done"]);
      expect(frames[0].data).toBe('{"x":"y"}');
    }
  });

  it("works one character at a time", () => {
    const text = ": ping\n\nevent: a\ndata: 1\n\n";
    const p = new SseParser();
    let comments = 0;
    const frames = [];
    for (const ch of text) {
      const r = p.push(ch);
      comments += r.comments;
      frames.push(...r.frames);
    }
    expect(comments).toBe(1);
    expect(frames).toEqual([{ event: "a", data: "1", id: null }]);
  });

  it("joins multi-line data with newlines", () => {
    const r = parseSse("event: x\ndata: line1\ndata: line2\ndata:\ndata: line4\n\n");
    expect(r.frames[0].data).toBe("line1\nline2\n\nline4");
  });

  it("counts ': ping' comments and emits no frame for them", () => {
    const r = new SseParser().push(": ping\n\n: ping\n\n");
    expect(r.frames).toEqual([]);
    expect(r.comments).toBe(2);
  });

  it("accepts CRLF and a CR/LF pair split across chunks", () => {
    const p = new SseParser();
    const a = p.push("event: a\r\ndata: 1\r");
    const b = p.push("\n\r\n");
    expect([...a.frames, ...b.frames]).toEqual([{ event: "a", data: "1", id: null }]);
  });

  it("defaults the event name to 'message' and tolerates a missing space after the colon", () => {
    expect(parseSse("data:hello\n\n").frames).toEqual([{ event: "message", data: "hello", id: null }]);
  });

  it("drops an unterminated trailing frame", () => {
    expect(new SseParser().push("event: a\ndata: 1\n").frames).toEqual([]);
  });
});
