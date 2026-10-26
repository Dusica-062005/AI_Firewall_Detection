import { applyCaption, liveSocketUrl, toPcm16 } from './live-call.service';

describe('live captions helpers', () => {
  it('adds new caption lines in order and replaces corrected ones', () => {
    let lines = applyCaption([], { index: 1, text: 'second', withheld: false });
    lines = applyCaption(lines, { index: 0, text: 'my ID is P nine four', withheld: false });
    lines = applyCaption(lines, { index: 0, text: 'my ID is [PATIENT_ID_1]', withheld: false });
    expect(lines.map((l) => l.text)).toEqual(['my ID is [PATIENT_ID_1]', 'second']);
  });

  it('resamples to 16 kHz 16-bit PCM and clips out-of-range samples', () => {
    const pcm = toPcm16(new Float32Array([0, 0.5, 1, 2, -2, -1]), 48000);
    expect(pcm.length).toBe(2);
    expect(pcm[0]).toBe(0);
    expect(pcm[1]).toBe(0x7fff); // every third sample at 48 kHz: 2.0 is clipped to full scale
    const same = toPcm16(new Float32Array([0.5, -0.5]), 16000);
    expect(Array.from(same)).toEqual([16383, -16383]);
    expect(same.buffer.byteLength).toBe(4); // owns its buffer, so the whole buffer can be sent
  });

  it('derives the WebSocket address from the API URL', () => {
    expect(liveSocketUrl('http://localhost:8000/api')).toBe('ws://localhost:8000/api/live');
    expect(liveSocketUrl('https://edge.example/api')).toBe('wss://edge.example/api/live');
    expect(liveSocketUrl('/api')).toBe(`ws://${location.host}/api/live`);
  });
});
