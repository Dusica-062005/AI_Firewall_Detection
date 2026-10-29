import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { Observable, startWith } from 'rxjs';

import {
  ApiError,
  AudioProcessResult,
  Channel,
  FirewallResult,
  ProcessingMode,
  ProfileInfo,
  SampleTranscript,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { LiveCallService, LiveStage } from '../../core/services/live-call.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { DurationPipe } from '../../shared/pipes/format.pipes';
import { InspectorStateService } from './inspector-state.service';
import { InspectorSummary } from './inspector-summary';

const DEFAULT_MAX_CHARS = 10000;

const LIVE_STAGE_LABELS: Record<LiveStage, string> = {
  transcribing: 'Transcribing the whole call (local)',
  protecting: 'Detecting and protecting',
  protected: 'Protected',
  local_ai: 'Local AI summary (on this machine)',
  cloud: 'Validated cloud handoff and cloud summary',
};

@Component({
  selector: 'app-inspector',
  imports: [ReactiveFormsModule, LucideDynamicIcon, DecimalPipe, DurationPipe, ErrorAlert, InspectorSummary],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './inspector.html',
  styleUrl: './inspector.scss',
})
export class Inspector implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly state = inject(InspectorStateService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly samples = signal<SampleTranscript[]>([]);
  protected readonly profiles = signal<ProfileInfo[]>([]);
  protected readonly maxChars = signal(DEFAULT_MAX_CHARS);
  protected readonly loadError = signal<ApiError | null>(null);
  protected readonly submitError = signal<ApiError | null>(null);
  protected readonly submitting = signal(false);
  protected readonly result = this.state.result;
  protected readonly submitted = this.state.submittedTranscript;
  protected readonly audio = this.state.audio;

  /** Text, an audio file, or a live call. Audio is transcribed on the local backend and never stored. */
  protected readonly inputKind = signal<'text' | 'audio' | 'live'>('text');
  /** Live redacted captions: microphone, or a recording streamed through the same live path. */
  protected readonly live = inject(LiveCallService);
  protected readonly liveFile = signal<File | null>(null);
  protected readonly liveActive = computed(() => ['connecting', 'live', 'processing'].includes(this.live.state()));
  /** The whole-call pass after End call: each stage, whether it finished, and how long it took. */
  protected readonly liveSteps = computed(() => {
    const steps = this.live.steps().filter((s) => s.stage !== 'protected');
    const now = this.live.now();
    const processing = this.live.state() === 'processing';
    return steps.map((step, i) => {
      const done = i < steps.length - 1 || !processing;
      const end = steps[i + 1]?.startedAt ?? (done ? step.startedAt : now);
      return { label: LIVE_STAGE_LABELS[step.stage], done, seconds: Math.max(0, Math.round((end - step.startedAt) / 1000)) };
    });
  });
  protected readonly audioFile = signal<File | null>(null);
  protected readonly audioError = signal<string | null>(null);
  protected readonly bleep = signal(true);
  /** Object URLs: the original plays from the local file only; the bleeped one from the response. */
  protected readonly originalUrl = signal<string | null>(null);
  protected readonly bleepedUrl = signal<string | null>(null);
  protected readonly isWav = computed(() => this.audioFile()?.name.toLowerCase().endsWith('.wav') ?? false);

  protected readonly modes: { value: ProcessingMode; label: string; hint: string }[] = [
    { value: 'inspect', label: 'Inspect only', hint: 'Detect and evaluate policy. No model or cloud call.' },
    { value: 'local', label: 'Local AI', hint: 'Adds a local summary when policy permits.' },
    { value: 'full', label: 'Full pipeline', hint: 'Adds the mock CloudLink handoff when policy authorizes it.' },
  ];
  protected readonly channels: Channel[] = ['voice', 'chat', 'email', 'sms'];

  protected readonly form = new FormGroup({
    sampleId: new FormControl('', { nonNullable: true }),
    transcript: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.maxLength(DEFAULT_MAX_CHARS)] }),
    profile: new FormControl('standard', { nonNullable: true, validators: [Validators.required] }),
    channel: new FormControl<Channel>('voice', { nonNullable: true }),
    mode: new FormControl<ProcessingMode>('full', { nonNullable: true }),
  });

  private readonly transcriptValue = toSignal(
    this.form.controls.transcript.valueChanges.pipe(startWith(this.form.controls.transcript.value)),
    { initialValue: '' },
  );
  private readonly modeValue = toSignal(
    this.form.controls.mode.valueChanges.pipe(startWith(this.form.controls.mode.value)),
    { initialValue: 'full' as ProcessingMode },
  );
  protected readonly charCount = computed(() => this.transcriptValue().length);
  protected readonly modeHint = computed(() => this.modes.find((m) => m.value === this.modeValue())?.hint ?? '');
  private readonly profileValue = toSignal(
    this.form.controls.profile.valueChanges.pipe(startWith(this.form.controls.profile.value)),
    { initialValue: 'standard' },
  );
  protected readonly selectedProfile = computed(
    () => this.profiles().find((p) => p.id === this.profileValue()) ?? null,
  );

  constructor() {
    this.destroyRef.onDestroy(() => {
      this.revokeUrls();
      if (this.liveActive()) {
        this.live.cancel(); // leaving the page mid-call: nothing is processed
      }
    });
    // A finished live call arrives as a normal audio result.
    effect(() => {
      const result = this.live.result();
      if (result) {
        untracked(() => this.applyAudioResult(result));
      }
    });
  }

  protected liveOptions() {
    const { profile, channel, mode } = this.form.getRawValue();
    return { profile, channel, mode, bleep: this.bleep() };
  }

  protected startLiveMicrophone(): void {
    this.submitError.set(null);
    void this.live.startMicrophone(this.liveOptions());
  }

  protected onLiveFile(event: Event): void {
    this.liveFile.set((event.target as HTMLInputElement).files?.[0] ?? null);
  }

  protected startLiveRecording(): void {
    const file = this.liveFile();
    if (file) {
      this.submitError.set(null);
      void this.live.startRecording(file, this.liveOptions());
    }
  }

  ngOnInit(): void {
    const bleeped = this.state.audio()?.bleep;
    if (bleeped) {
      this.bleepedUrl.set(audioUrl(bleeped.audio_base64, bleeped.content_type));
    }
    this.form.setValue(this.state.draft(), { emitEvent: true });
    this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.state.draft.set(this.form.getRawValue());
    });
    this.loadReferenceData();
  }

  protected loadReferenceData(): void {
    this.loadError.set(null);
    this.api.samples().subscribe({
      next: (samples) => this.samples.set(samples),
      error: (err: ApiError) => this.loadError.set(err),
    });
    this.api.profiles().subscribe({
      next: (res) => this.profiles.set(res.items),
      error: (err: ApiError) => this.loadError.set(err),
    });
    this.api.appConfig().subscribe({
      next: (config) => {
        this.maxChars.set(config.max_transcript_chars);
        const control = this.form.controls.transcript;
        control.setValidators([Validators.required, Validators.maxLength(config.max_transcript_chars)]);
        control.updateValueAndValidity({ emitEvent: false });
      },
      error: () => {
        // Keep the default limit; the backend enforces its own limit regardless.
      },
    });
  }

  protected loadSample(): void {
    const sample = this.samples().find((s) => s.id === this.form.controls.sampleId.value);
    if (!sample) {
      return;
    }
    this.form.patchValue({ transcript: sample.transcript, profile: sample.profile, channel: sample.channel });
    this.form.controls.transcript.markAsTouched();
  }

  protected clear(): void {
    this.form.patchValue({ transcript: '', sampleId: '' });
    this.form.controls.transcript.markAsUntouched();
    this.state.result.set(null);
    this.state.submittedTranscript.set('');
    this.state.audio.set(null);
    this.selectFile(null);
    this.submitError.set(null);
  }

  protected onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectFile(input.files?.[0] ?? null);
  }

  private selectFile(file: File | null): void {
    const old = this.originalUrl();
    if (old) {
      URL.revokeObjectURL(old);
    }
    this.audioFile.set(file);
    this.audioError.set(null);
    this.originalUrl.set(file ? URL.createObjectURL(file) : null);
  }

  private revokeUrls(): void {
    for (const url of [this.originalUrl(), this.bleepedUrl()]) {
      if (url) {
        URL.revokeObjectURL(url);
      }
    }
  }

  protected submit(): void {
    if (this.inputKind() === 'audio') {
      this.submitAudio();
      return;
    }
    if (this.inputKind() === 'live') {
      return; // live calls start and end with their own buttons
    }
    this.form.markAllAsTouched();
    if (this.form.invalid || this.submitting()) {
      return;
    }
    const { transcript, profile, channel, mode } = this.form.getRawValue();
    this.submitting.set(true);
    this.submitError.set(null);
    const request$: Observable<FirewallResult> =
      mode === 'inspect'
        ? this.api.inspect({ transcript, profile, channel })
        : this.api.process({ transcript, profile, channel, mode });
    request$.subscribe({
      next: (result) => {
        this.state.submittedTranscript.set(transcript);
        this.state.result.set(result);
        this.state.audio.set(null);
        this.submitting.set(false);
      },
      error: (err: ApiError) => {
        this.submitError.set(err);
        this.submitting.set(false);
      },
    });
  }

  private submitAudio(): void {
    const file = this.audioFile();
    if (!file) {
      this.audioError.set('Choose a .wav, .mp3 or .m4a file.');
      return;
    }
    if (this.submitting()) {
      return;
    }
    const { profile, channel, mode } = this.form.getRawValue();
    const bleep = this.bleep() && this.isWav();
    this.submitting.set(true);
    this.submitError.set(null);
    this.api.processAudio(file, profile, channel, mode, bleep).subscribe({
      next: (result) => {
        this.applyAudioResult(result);
        this.submitting.set(false);
      },
      error: (err: ApiError) => {
        this.submitError.set(err);
        this.submitting.set(false);
      },
    });
  }

  /** Show an audio result (uploaded file or finished live call) the same way. */
  private applyAudioResult(result: AudioProcessResult): void {
    const old = this.bleepedUrl();
    if (old) {
      URL.revokeObjectURL(old);
    }
    this.bleepedUrl.set(result.bleep ? audioUrl(result.bleep.audio_base64, result.bleep.content_type) : null);
    this.state.submittedTranscript.set(result.transcription.transcript ?? '');
    this.state.audio.set({ transcription: result.transcription, bleep: result.bleep });
    this.state.result.set(result);
  }
}

/** A playable URL for audio returned as base64. Revoked when replaced or when the page closes. */
function audioUrl(base64: string, type: string): string {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return URL.createObjectURL(new Blob([bytes], { type }));
}
