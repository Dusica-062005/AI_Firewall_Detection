import { Injectable, signal } from '@angular/core';

import { BleepInfo, Channel, FirewallResult, ProcessingMode, TranscriptionInfo } from '../../core/models/api.models';

export interface InspectorDraft {
  transcript: string;
  profile: string;
  channel: Channel;
  mode: ProcessingMode;
  sampleId: string;
}

/**
 * Keeps the Inspector input and last result in memory while navigating between pages
 * during a demo. Nothing is written to browser storage.
 */
@Injectable({ providedIn: 'root' })
export class InspectorStateService {
  readonly draft = signal<InspectorDraft>({
    transcript: '',
    profile: 'standard',
    channel: 'voice',
    mode: 'full',
    sampleId: '',
  });
  readonly result = signal<FirewallResult | null>(null);
  readonly submittedTranscript = signal<string>('');
  /** Audio input: the local transcription and, when requested, the bleeped audio. */
  readonly audio = signal<{ transcription: TranscriptionInfo; bleep: BleepInfo | null } | null>(null);
}
