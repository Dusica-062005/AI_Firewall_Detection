import { Injectable, inject, signal } from '@angular/core';

import { AudioProcessResult, Channel, ProcessingMode } from '../models/api.models';
import { RuntimeConfigService } from './runtime-config.service';

/**
 * Live redacted captions: streams microphone audio (or a recording, for a reliable demo) to the
 * local backend over a WebSocket and shows captions with protected values already replaced.
 * Captions stay on this computer; when the call ends the backend runs the normal pipeline once.
 */

export interface LiveCaption {
  index: number;
  text: string;
  withheld: boolean;
}

export type LiveState = 'idle' | 'connecting' | 'live' | 'processing' | 'done' | 'error';
export type LiveSource = 'microphone' | 'recording';

/** Stages of the whole-call pass after End call, in the order the backend reports them. */
export type LiveStage = 'transcribing' | 'protecting' | 'protected' | 'local_ai' | 'cloud';

export interface LiveStep {
  stage: LiveStage;
  startedAt: number;
}

/** The final protected transcript, available before the model calls finish. */
export interface LivePreview {
  decision: string;
  redactedTranscript: string;
}

export interface LiveOptions {
  profile: string;
  channel: Channel;
  mode: ProcessingMode;
  bleep: boolean;
}

const TARGET_RATE = 16000;
const SEND_EVERY_MS = 250;

/** Apply one caption message: a new line, or a corrected version of an earlier one. */
export function applyCaption(lines: LiveCaption[], message: LiveCaption): LiveCaption[] {
  const next = lines.filter((line) => line.index !== message.index);
  next.push({ index: message.index, text: message.text, withheld: message.withheld });
  return next.sort((a, b) => a.index - b.index);
}

/** Resample float audio to 16 kHz and convert it to 16-bit PCM (linear interpolation). */
export function toPcm16(samples: Float32Array, fromRate: number): Int16Array<ArrayBuffer> {
  const length = Math.floor((samples.length * TARGET_RATE) / fromRate);
  const out = new Int16Array(length);
  const step = fromRate / TARGET_RATE;
  for (let i = 0; i < length; i++) {
    const pos = i * step;
    const left = Math.floor(pos);
    const right = Math.min(left + 1, samples.length - 1);
    const value = samples[left] + (samples[right] - samples[left]) * (pos - left);
    out[i] = Math.max(-1, Math.min(1, value)) * 0x7fff;
  }
  return out;
}

/** The WebSocket address for a configured API URL such as http://localhost:8000/api. */
export function liveSocketUrl(apiBaseUrl: string): string {
  if (/^https?:\/\//.test(apiBaseUrl)) {
    return `${apiBaseUrl.replace(/^http/, 'ws')}/live`;
  }
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}${apiBaseUrl}/live`;
}

const WORKLET = `
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
`;

@Injectable({ providedIn: 'root' })
export class LiveCallService {
  private readonly config = inject(RuntimeConfigService);

  readonly state = signal<LiveState>('idle');
  readonly source = signal<LiveSource | null>(null);
  readonly captions = signal<LiveCaption[]>([]);
  readonly seconds = signal(0);
  readonly error = signal<string | null>(null);
  readonly result = signal<AudioProcessResult | null>(null);
  readonly steps = signal<LiveStep[]>([]);
  readonly preview = signal<LivePreview | null>(null);
  /** Ticks every second while the whole call is processed, for the elapsed times. */
  readonly now = signal(Date.now());

  private socket: WebSocket | null = null;
  private clock: ReturnType<typeof setInterval> | null = null;
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private player: AudioBufferSourceNode | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private pending: Float32Array[] = [];

  /** Start a call from the microphone. */
  async startMicrophone(options: LiveOptions): Promise<void> {
    await this.begin('microphone', options, async (context) => {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
      await context.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      const capture = new AudioWorkletNode(context, 'pcm-capture');
      capture.port.onmessage = (event: MessageEvent<Float32Array>) => this.pending.push(event.data);
      context.createMediaStreamSource(this.stream).connect(capture);
      this.timer = setInterval(() => this.flush(context.sampleRate), SEND_EVERY_MS);
    });
  }

  /** Stream a recording at real-time pace, playing it aloud, through the same live path. */
  async startRecording(file: File, options: LiveOptions): Promise<void> {
    await this.begin('recording', options, async (context) => {
      const audio = await context.decodeAudioData(await file.arrayBuffer());
      const mono = new Float32Array(audio.length);
      for (let c = 0; c < audio.numberOfChannels; c++) {
        const data = audio.getChannelData(c);
        for (let i = 0; i < data.length; i++) {
          mono[i] += data[i] / audio.numberOfChannels;
        }
      }
      const pcm = toPcm16(mono, audio.sampleRate);
      this.player = context.createBufferSource();
      this.player.buffer = audio;
      this.player.connect(context.destination);
      this.player.start();
      const slice = (TARGET_RATE * SEND_EVERY_MS) / 1000;
      let offset = 0;
      this.timer = setInterval(() => {
        if (offset >= pcm.length) {
          this.stop();
          return;
        }
        this.send(pcm.slice(offset, offset + slice));
        offset += slice;
      }, SEND_EVERY_MS);
    });
  }

  /** End the call: the backend transcribes it all and runs the normal pipeline once. */
  stop(): void {
    if (this.state() !== 'live') {
      return;
    }
    if (this.context) {
      this.flush(this.context.sampleRate);
    }
    this.stopCapture();
    this.state.set('processing');
    this.now.set(Date.now());
    this.clock = setInterval(() => this.now.set(Date.now()), 1000);
    this.socket?.send(JSON.stringify({ type: 'stop' }));
  }

  /** Leave without processing: the backend drops the audio and records nothing. */
  cancel(): void {
    this.stopCapture();
    this.socket?.close();
    this.socket = null;
    if (this.state() !== 'done') {
      this.state.set('idle');
    }
  }

  private async begin(source: LiveSource, options: LiveOptions, capture: (context: AudioContext) => Promise<void>): Promise<void> {
    this.cancel();
    this.source.set(source);
    this.captions.set([]);
    this.seconds.set(0);
    this.error.set(null);
    this.result.set(null);
    this.steps.set([]);
    this.preview.set(null);
    this.state.set('connecting');
    try {
      await this.connect(options);
      this.context = new AudioContext();
      await capture(this.context);
      this.state.set('live');
    } catch (err) {
      this.fail(err instanceof Error ? err.message : 'The live call could not start.');
    }
  }

  private connect(options: LiveOptions): Promise<void> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(liveSocketUrl(this.config.apiBaseUrl));
      socket.binaryType = 'arraybuffer';
      this.socket = socket;
      socket.onopen = () => socket.send(JSON.stringify({ type: 'start', ...options }));
      socket.onerror = () => reject(new Error('The firewall backend is not reachable for live calls.'));
      socket.onclose = () => {
        if (this.state() === 'live' || this.state() === 'processing') {
          this.fail('The live connection closed before the call was processed.');
        }
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        const message = JSON.parse(event.data);
        switch (message.type) {
          case 'ready':
            resolve();
            break;
          case 'caption':
            this.captions.update((lines) => applyCaption(lines, message));
            break;
          case 'status':
            this.seconds.set(message.seconds);
            break;
          case 'progress':
            this.steps.update((steps) => [...steps, { stage: message.stage, startedAt: Date.now() }]);
            if (message.stage === 'protected') {
              this.preview.set({ decision: message.decision, redactedTranscript: message.redacted_transcript });
            }
            break;
          case 'result':
            this.stopClock();
            this.result.set(message.result as AudioProcessResult);
            this.state.set('done');
            this.socket = null;
            break;
          case 'error':
            this.fail(message.message);
            reject(new Error(message.message));
            break;
        }
      };
    });
  }

  private flush(rate: number): void {
    if (!this.pending.length) {
      return;
    }
    const total = this.pending.reduce((n, chunk) => n + chunk.length, 0);
    const joined = new Float32Array(total);
    let at = 0;
    for (const chunk of this.pending) {
      joined.set(chunk, at);
      at += chunk.length;
    }
    this.pending = [];
    this.send(toPcm16(joined, rate));
  }

  private send(pcm: Int16Array<ArrayBuffer>): void {
    if (this.socket?.readyState === WebSocket.OPEN && pcm.length) {
      this.socket.send(pcm); // each array owns its buffer: toPcm16 and slice() both copy
    }
  }

  private stopClock(): void {
    if (this.clock) {
      clearInterval(this.clock);
      this.clock = null;
    }
  }

  private stopCapture(): void {
    this.stopClock();
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    try {
      this.player?.stop();
    } catch {
      // already stopped
    }
    this.player = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    void this.context?.close();
    this.context = null;
    this.pending = [];
  }

  private fail(message: string): void {
    this.stopCapture();
    this.error.set(message);
    this.state.set('error');
    this.socket?.close();
    this.socket = null;
  }
}
