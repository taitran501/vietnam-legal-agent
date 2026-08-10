import { describe, expect, it } from 'vitest';
import { parseSSEEvent } from './sseParser';

describe('parseSSEEvent', () => {
  it('reads a JSON event framed with CRLF', () => {
    expect(
      parseSSEEvent('data: {"type":"response_chunk","chunk":"Điều 77"}\r\n')
    ).toEqual({ type: 'response_chunk', chunk: 'Điều 77' });
  });

  it('ignores keepalive comments and malformed frames', () => {
    expect(parseSSEEvent(': keepalive\n\n')).toBeNull();
    expect(parseSSEEvent('data: not-json\n\n')).toBeNull();
  });
});
