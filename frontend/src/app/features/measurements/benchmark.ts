import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, BenchmarkLatest, BenchmarkLevel } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { DurationPipe } from '../../shared/pipes/format.pipes';

const POLL_MS = 2000;
const STAGE_LABELS: Record<string, string> = {
  transcription: 'Transcription', detection: 'Detection', policy: 'Policy', protection: 'Protection',
  local_ai: 'Local AI summary', cloud: 'Cloud handoff', total: 'Total',
};

/** Benchmark tab (NFR-2, NFR-3): measured latency per stage and throughput per concurrency level. */
@Component({
  selector: 'app-benchmark',
  imports: [DatePipe, RouterLink, LucideDynamicIcon, StatusBadge, ErrorAlert, DurationPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card">
      <div class="card-header">
        <h2><svg class="icon" lucideIcon="timer" aria-hidden="true"></svg>Latency benchmark</h2>
        @if (latest()?.run; as r) { <app-status-badge [value]="r.status" /> }
      </div>
      <div class="card-body stack">
        <p class="text-sm muted">Times the full pipeline on synthetic samples. The first (cold) call is reported separately.</p>
        <div class="row wrap">
          <label class="field calls-field">
            <span class="field__label">Calls per concurrency level</span>
            <input class="input" type="number" min="1" max="200" [value]="calls()"
                   (change)="calls.set(+$any($event.target).value || 20)" [disabled]="running()" />
          </label>
          <label class="checkbox">
            <input type="checkbox" [checked]="withAudio()" (change)="withAudio.set($any($event.target).checked)" [disabled]="running()" />
            Include transcription (synthetic audio clips)
          </label>
          <button type="button" class="btn btn-primary" (click)="run()" [disabled]="running() || loading()">
            @if (running()) { <span class="spinner" aria-hidden="true"></span> }
            <svg class="icon" lucideIcon="play" aria-hidden="true"></svg>Run benchmark
          </button>
        </div>
        <app-error-alert [error]="error()" title="The benchmark could not run" [retryable]="true" (retry)="load()" />
        @if (latest()?.run; as r) {
          @if (r.status === 'RUNNING') {
            <div class="progress" role="progressbar" aria-label="Benchmark progress" [attr.aria-valuenow]="r.progress_done"
                 aria-valuemin="0" [attr.aria-valuemax]="r.progress_total">
              <div class="progress__bar" [style.width.%]="r.progress_total ? (r.progress_done / r.progress_total) * 100 : 0"></div>
            </div>
            <span class="text-xs muted">Running: {{ r.progress_done }} / {{ r.progress_total }} calls. Local model calls take several seconds each.</span>
          } @else if (r.status === 'FAILED') {
            <div class="alert alert-error"><svg class="icon" lucideIcon="circle-x" aria-hidden="true"></svg><span>Run {{ r.run_id }} failed: {{ r.error }}</span></div>
          }
        }
      </div>

      @if (latest()?.completed; as c) {
        <div class="card-body stack">
          <div class="verdict">
            <app-status-badge [value]="c.verdict" [strong]="true" />
            <span class="text-sm">{{ c.verdict_reason }}</span>
          </div>
          <dl class="kv kv--inline text-sm">
            <dt>Run</dt><dd class="mono">{{ c.run_id }}</dd>
            <dt>When</dt><dd>{{ c.created_at | date: 'MMM d, y, HH:mm' }} ({{ c.duration_s }} s)</dd>
            <dt>Machine</dt>
            <dd>{{ c.machine.cpu }}, {{ c.machine.physical_cores ?? '?' }} cores / {{ c.machine.logical_cores ?? '?' }} threads,
              {{ c.machine.ram_gb ?? '?' }} GB RAM, GPU {{ c.models.gpu ?? 'not detected' }}</dd>
            <dt>Models</dt>
            <dd>Local {{ c.models.local }}; cloud stand-in {{ c.models.cloud_stand_in ?? 'not configured' }};
              transcription {{ c.config.include_transcription ? c.models.whisper : 'not included' }}; Ollama {{ c.models.ollama_version ?? '-' }}</dd>
            <dt>Cold first call</dt><dd>{{ c.cold?.stages?.['total'] | duration }} (excluded from the statistics)</dd>
          </dl>
          <a class="text-sm" routerLink="/sizing">Size a deployment from this benchmark</a>
        </div>
        @for (level of c.levels; track level.concurrency) {
          <div class="card-body card-body--flush table-wrap">
            <table class="data-table">
              <caption class="level-caption">
                Concurrency {{ level.concurrency }}: n={{ level.n_calls }} calls,
                <strong>{{ level.calls_per_minute ?? '-' }} calls/min</strong>
                @for (f of failures(level); track f[0]) { <span class="tag tag--bad">{{ f[0] }} failed x{{ f[1] }}</span> }
              </caption>
              <thead>
                <tr><th scope="col">Stage</th><th scope="col" class="num">n</th><th scope="col" class="num">Mean</th>
                  <th scope="col" class="num">p50</th><th scope="col" class="num">p95</th><th scope="col" class="num">Max</th></tr>
              </thead>
              <tbody>
                @for (stage of stages; track stage) {
                  @if (level.stages[stage]; as s) {
                    <tr [class.row--total]="stage === 'total'">
                      <td>{{ label(stage) }}</td><td class="num">{{ s.n }}</td><td class="num">{{ s.mean_ms | duration }}</td>
                      <td class="num">{{ s.p50_ms | duration }}</td><td class="num">{{ s.p95_ms | duration }}</td><td class="num">{{ s.max_ms | duration }}</td>
                    </tr>
                  }
                }
              </tbody>
            </table>
          </div>
        }
      } @else if (!loading()) {
        <div class="empty-state">
          <svg class="icon" lucideIcon="timer" aria-hidden="true"></svg>
          <span class="empty-state__title">Not measured yet</span>
          <span>Run a benchmark to measure latency on this machine.</span>
        </div>
      }
    </section>
  `,
  styles: `
    .calls-field .input { width: 120px; }
    .verdict { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
    .level-caption { text-align: left; padding: var(--s-3) var(--s-4); font-size: var(--fs-sm); }
    .row--total td { font-weight: 600; background: var(--c-surface-muted); }
    .tag--bad { background: var(--c-error-bg); color: var(--c-error); margin-left: var(--s-2); }
    .progress { height: 8px; border-radius: 4px; background: var(--c-neutral-bg); overflow: hidden; }
    .progress__bar { height: 100%; background: var(--c-blue); transition: width 0.3s ease; }
  `,
})
export class BenchmarkTab implements OnInit {
  private readonly api = inject(FirewallApiService);
  private poll: ReturnType<typeof setInterval> | null = null;

  protected readonly latest = signal<BenchmarkLatest | null>(null);
  protected readonly loading = signal(true);
  protected readonly starting = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly calls = signal(20);
  protected readonly withAudio = signal(false);
  protected readonly running = computed(() => this.starting() || this.latest()?.run?.status === 'RUNNING');
  protected readonly stages = Object.keys(STAGE_LABELS);

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.api.benchmarkLatest().subscribe({
      next: (latest) => {
        this.latest.set(latest);
        this.loading.set(false);
        if (latest.run?.status === 'RUNNING') {
          this.poll ??= setInterval(() => this.load(), POLL_MS);
        } else {
          this.stopPolling();
        }
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
        this.stopPolling();
      },
    });
  }

  protected run(): void {
    this.starting.set(true);
    this.error.set(null);
    this.api.startBenchmark({ calls_per_level: this.calls(), include_transcription: this.withAudio() }).subscribe({
      next: () => {
        this.starting.set(false);
        this.load();
      },
      error: (err: ApiError) => {
        this.starting.set(false);
        this.error.set(err);
      },
    });
  }

  protected label(stage: string): string {
    return STAGE_LABELS[stage] ?? stage;
  }

  protected failures(level: BenchmarkLevel): [string, number][] {
    return Object.entries(level.failures);
  }

  private stopPolling(): void {
    if (this.poll) {
      clearInterval(this.poll);
      this.poll = null;
    }
  }
}
