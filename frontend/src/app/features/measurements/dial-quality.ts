import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, DialPosition, QualityLatest, QualityPositionScore } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';
import { score } from './measurement-format';

const POLL_MS = 2000;
export const POSITION_LABELS: Record<DialPosition, string> = {
  max_privacy: 'Maximum privacy',
  balanced: 'Balanced',
  max_quality: 'Maximum quality',
};
export const QUALITY_NOTE =
  'Similarity of the protected summary to the raw-text summary (not a human rating).';

/** Dial quality tab (Feature 4): measured similarity per dial position, from the latest completed run. */
@Component({
  selector: 'app-dial-quality',
  imports: [DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card" id="quality">
      <div class="card-header">
        <h2><svg class="icon" lucideIcon="gauge" aria-hidden="true"></svg>Dial quality score</h2>
        @if (latest()?.run; as r) { <app-status-badge [value]="r.status" /> }
      </div>
      <div class="card-body stack">
        <p class="text-sm muted">{{ note }}</p>
        <div class="row wrap">
          <button type="button" class="btn btn-primary" (click)="run()" [disabled]="running() || loading()">
            @if (running()) { <span class="spinner" aria-hidden="true"></span> }
            <svg class="icon" lucideIcon="play" aria-hidden="true"></svg>Run quality measurement
          </button>
          @if (latest()?.run; as r) {
            @if (r.status === 'RUNNING') {
              <span class="text-xs muted">Running: {{ r.progress_done }} / {{ r.progress_total }} steps</span>
            }
          }
        </div>
        <app-error-alert [error]="error()" title="The quality measurement could not run" [retryable]="true" (retry)="load()" />
        @if (latest()?.run; as r) {
          @if (r.status === 'FAILED') {
            <div class="alert alert-error">
              <svg class="icon" lucideIcon="circle-x" aria-hidden="true"></svg>
              <span>Run {{ r.run_id }} failed: {{ r.error }}</span>
            </div>
          }
        }
      </div>

      @if (latest()?.completed; as c) {
        <div class="card-body stack quality-scores">
          @for (p of c.positions; track p.position) {
            <div class="quality-row">
              <span class="quality-row__label">{{ label(p) }}</span>
              <div class="quality-bar" role="img" [attr.aria-label]="label(p) + ' score ' + fmt(p.score)">
                @if (p.score !== null) { <div class="quality-bar__fill" [style.width.%]="p.score * 100"></div> }
              </div>
              <span class="quality-row__value mono">{{ fmt(p.score) }}</span>
              <span class="text-xs muted">n={{ p.n }}{{ p.n_null ? ', ' + p.n_null + ' without a summary' : '' }}</span>
            </div>
          }
          <div class="quality-row" aria-hidden="true">
            <span></span>
            <div class="quality-axis text-xs muted"><span>0</span><span>0.5</span><span>1</span></div>
          </div>
          <dl class="kv kv--inline text-sm">
            <dt>Run</dt><dd class="mono">{{ c.run_id }}</dd>
            <dt>When</dt><dd>{{ c.created_at | date: 'MMM d, y, HH:mm:ss' }} ({{ c.duration_s }} s)</dd>
            <dt>Models</dt><dd>Reference {{ c.reference_model }}; local {{ c.local_model }}; cloud stand-in {{ c.cloud_model ?? 'not configured' }}; embeddings {{ c.embed_model }}</dd>
            <dt>Machine</dt><dd>{{ c.machine }}</dd>
          </dl>
        </div>
        <div class="card-body card-body--flush table-wrap">
          <table class="data-table">
            <thead>
              <tr><th scope="col">Sample</th><th scope="col">Position</th><th scope="col">Decision</th><th scope="col">Summary from</th><th scope="col" class="num">Similarity</th></tr>
            </thead>
            <tbody>
              @for (s of c.samples; track s.sample_id + s.position) {
                <tr>
                  <td>{{ s.title }}</td>
                  <td>{{ positionLabel(s.position) }}</td>
                  <td><app-status-badge [value]="s.decision" /></td>
                  <td>{{ s.source | humanize }}</td>
                  <td class="num mono">{{ s.similarity === null ? 'No summary' : s.similarity.toFixed(3) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else if (!loading()) {
        <div class="empty-state">
          <svg class="icon" lucideIcon="gauge" aria-hidden="true"></svg>
          <span class="empty-state__title">Not measured yet</span>
          <span>Needs the embedding model: ollama pull nomic-embed-text</span>
        </div>
      }
    </section>
  `,
  styles: `
    .quality-scores {
      gap: var(--s-2);
    }
    .quality-row {
      display: grid;
      grid-template-columns: 140px minmax(0, 1fr) 48px auto;
      align-items: center;
      gap: var(--s-3);
      @media (max-width: 720px) {
        grid-template-columns: minmax(0, 1fr) 48px;
      }
    }
    .quality-row__label {
      font-weight: 600;
      font-size: var(--fs-sm);
    }
    .quality-row__value {
      text-align: right;
      font-weight: 600;
    }
    .quality-bar {
      height: 12px;
      border-radius: 6px;
      background: var(--c-neutral-bg);
      overflow: hidden;
    }
    .quality-bar__fill {
      height: 100%;
      background: var(--c-blue);
    }
    .quality-axis {
      display: flex;
      justify-content: space-between;
      margin-top: -4px;
      @media (max-width: 720px) {
        display: none;
      }
    }
  `,
})
export class DialQuality implements OnInit {
  private readonly api = inject(FirewallApiService);
  private poll: ReturnType<typeof setInterval> | null = null;

  protected readonly latest = signal<QualityLatest | null>(null);
  protected readonly loading = signal(true);
  protected readonly starting = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly running = computed(() => this.starting() || this.latest()?.run?.status === 'RUNNING');
  protected readonly note = QUALITY_NOTE;
  protected readonly fmt = score;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  ngOnInit(): void {
    this.load();
  }

  /** Public so the page's Refresh button can reload this tab. */
  load(): void {
    this.api.qualityLatest().subscribe({
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
    this.api.startQualityRun().subscribe({
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

  protected label(p: QualityPositionScore): string {
    return POSITION_LABELS[p.position];
  }

  protected positionLabel(position: DialPosition): string {
    return POSITION_LABELS[position];
  }

  private stopPolling(): void {
    if (this.poll) {
      clearInterval(this.poll);
      this.poll = null;
    }
  }
}
