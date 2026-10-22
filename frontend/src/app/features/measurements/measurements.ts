import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';
import { forkJoin } from 'rxjs';

import {
  ApiError,
  CanaryBucket,
  CanaryCompare,
  CanaryRunDetail,
  CanaryRunSummary,
  CanarySetSummary,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { HumanizePipe } from '../../shared/pipes/format.pipes';
import { DialQuality } from './dial-quality';
import { delta, pct, trend } from './measurement-format';

export type MeasurementTab = 'canaries' | 'languages' | 'quality';

const TABS: { id: MeasurementTab; label: string }[] = [
  { id: 'canaries', label: 'Leak canaries' },
  { id: 'languages', label: 'Languages' },
  { id: 'quality', label: 'Dial quality' },
];
const POLL_MS = 1500;
const LANGUAGE_NAMES: Record<string, string> = {
  en: 'English', hinglish: 'Hinglish', hi: 'Hindi', kn: 'Kannada', ta: 'Tamil',
};

/**
 * Measurements (Features 4, 5, 6): every number shown comes from a stored run, with n, run ID,
 * rule version and machine. With no run, the page says "Not measured yet".
 */
@Component({
  selector: 'app-measurements',
  imports: [DatePipe, LucideDynamicIcon, ErrorAlert, HumanizePipe, DialQuality],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './measurements.html',
  styleUrl: './measurements.scss',
})
export class Measurements implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);
  private readonly router = inject(Router);
  private readonly fragment = toSignal(inject(ActivatedRoute).fragment);
  private poll: ReturnType<typeof setInterval> | null = null;

  protected readonly tabs = TABS;
  protected readonly current = computed<MeasurementTab>(() => TABS.find((t) => t.id === this.fragment())?.id ?? 'canaries');

  protected readonly canarySet = signal<CanarySetSummary | null>(null);
  protected readonly runs = signal<CanaryRunSummary[]>([]);
  /** The most recent completed run: the source of every number on the page. */
  protected readonly detail = signal<CanaryRunDetail | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<ApiError | null>(null);
  protected readonly startError = signal<ApiError | null>(null);
  protected readonly starting = signal(false);
  protected readonly normalize = signal(true);

  /** The newest run when it is not completed: shows progress (RUNNING) or the reason (FAILED). */
  protected readonly active = computed(() => {
    const newest = this.runs()[0];
    return newest && newest.status !== 'COMPLETED' ? newest : null;
  });
  protected readonly running = computed(() => this.starting() || this.active()?.status === 'RUNNING');
  protected readonly completedRuns = computed(() => this.runs().filter((r) => r.status === 'COMPLETED'));
  protected readonly metrics = computed(() => this.detail()?.metrics ?? null);
  protected readonly languageRows = computed(() =>
    (this.metrics()?.by_script ?? []).map((b) => {
      const [language, script] = b.key.split('/');
      return { ...b, language: LANGUAGE_NAMES[language] ?? language, script };
    }),
  );

  protected readonly compareA = signal('');
  protected readonly compareB = signal('');
  protected readonly comparison = signal<CanaryCompare | null>(null);
  protected readonly compareError = signal<ApiError | null>(null);
  protected readonly comparing = signal(false);

  protected readonly pct = pct;
  protected readonly delta = delta;
  protected readonly trend = trend;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopPolling());
  }

  ngOnInit(): void {
    this.load();
  }

  protected select(tab: MeasurementTab): void {
    this.router.navigate([], { fragment: tab, queryParamsHandling: 'preserve' });
  }

  protected onTabKey(event: KeyboardEvent): void {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) {
      return;
    }
    const index = TABS.findIndex((t) => t.id === this.current());
    const next = TABS[(index + step + TABS.length) % TABS.length];
    this.select(next.id);
    queueMicrotask(() => document.getElementById('mtab-' + next.id)?.focus());
    event.preventDefault();
  }

  protected load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    forkJoin({ set: this.api.canarySet(), runs: this.api.canaryRuns() }).subscribe({
      next: ({ set, runs }) => {
        this.canarySet.set(set);
        this.applyRuns(runs);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.loadError.set(err);
        this.loading.set(false);
      },
    });
  }

  private applyRuns(runs: CanaryRunSummary[]): void {
    const previousCompleted = this.completedRuns()[0]?.run_id;
    this.runs.set(runs);
    const latest = this.completedRuns()[0];
    if (latest && latest.run_id !== previousCompleted) {
      this.api.canaryRun(latest.run_id).subscribe({
        next: (detail) => this.detail.set(detail),
        error: (err: ApiError) => this.loadError.set(err),
      });
    } else if (!latest) {
      this.detail.set(null);
    }
    const completed = this.completedRuns();
    if (completed.length >= 2 && !this.compareA()) {
      this.compareA.set(completed[1].run_id);
      this.compareB.set(completed[0].run_id);
    }
    if (this.active()?.status === 'RUNNING') {
      this.startPolling();
    } else {
      this.stopPolling();
    }
  }

  protected run(): void {
    this.starting.set(true);
    this.startError.set(null);
    this.api.startCanaryRun(this.normalize()).subscribe({
      next: () => {
        this.starting.set(false);
        this.notify.success('Canary batch started. Every call goes through the real pipeline.');
        this.refreshRuns();
      },
      error: (err: ApiError) => {
        this.starting.set(false);
        this.startError.set(err);
      },
    });
  }

  private refreshRuns(): void {
    this.api.canaryRuns().subscribe({
      next: (runs) => this.applyRuns(runs),
      error: (err: ApiError) => {
        this.loadError.set(err);
        this.stopPolling();
      },
    });
  }

  private startPolling(): void {
    this.poll ??= setInterval(() => this.refreshRuns(), POLL_MS);
  }

  private stopPolling(): void {
    if (this.poll) {
      clearInterval(this.poll);
      this.poll = null;
    }
  }

  protected compare(): void {
    const a = this.compareA();
    const b = this.compareB();
    if (!a || !b || a === b) {
      return;
    }
    this.comparing.set(true);
    this.compareError.set(null);
    this.api.compareCanaryRuns(a, b).subscribe({
      next: (result) => {
        this.comparison.set(result);
        this.comparing.set(false);
      },
      error: (err: ApiError) => {
        this.compareError.set(err);
        this.comparing.set(false);
      },
    });
  }

  protected runLabel(run: CanaryRunSummary): string {
    const when = new Date(run.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    return `${when} - normalization ${run.normalize_on ? 'on' : 'off'}${run.kill_switch_on ? ', kill switch on' : ''} (${run.run_id.slice(-6)})`;
  }

  protected progress(run: CanaryRunSummary): number {
    return run.progress_total ? Math.round((run.progress_done / run.progress_total) * 100) : 0;
  }

  protected counts(record: Record<string, number> | undefined): [string, number][] {
    return Object.entries(record ?? {});
  }

  protected bucketTitle(group: string, bucket: CanaryBucket | null, key: string): string {
    return group === 'language' ? (LANGUAGE_NAMES[key] ?? key) : (bucket?.key ?? key);
  }
}
