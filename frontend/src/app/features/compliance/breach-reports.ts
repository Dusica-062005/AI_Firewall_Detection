import { DatePipe, KeyValuePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import {
  ApiError,
  BreachReport,
  BreachReportSource,
  BreachReportVerify,
  CanaryRunSummary,
  Incident,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ConfirmDialog } from '../../shared/components/confirm-dialog';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';

/**
 * Breach Report Generator (Feature 8): drafts built from stored records for a compliance officer
 * to review. The page never sends, files or emails anything.
 */
@Component({
  selector: 'app-breach-reports',
  imports: [DatePipe, KeyValuePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, ConfirmDialog, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './breach-reports.html',
  styleUrl: './compliance.scss',
  host: { '(document:keydown.escape)': 'close()' },
})
export class BreachReports implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  protected readonly items = signal<BreachReport[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);

  protected readonly source = signal<BreachReportSource>('canary_run');
  protected readonly ref = signal('');
  protected readonly from = signal('');
  protected readonly to = signal('');
  protected readonly leakyRuns = signal<CanaryRunSummary[]>([]);
  protected readonly exposures = signal<Incident[]>([]);
  protected readonly drafting = signal(false);
  protected readonly draftError = signal<ApiError | null>(null);

  protected readonly selectedId = signal<string | null>(null);
  protected readonly selected = computed(() => this.items().find((r) => r.report_id === this.selectedId()) ?? null);
  protected readonly verify = signal<BreachReportVerify | null>(null);
  protected readonly reviewer = signal('');
  protected readonly busy = signal(false);
  protected readonly actionError = signal<ApiError | null>(null);
  /** The report awaiting confirmation before it is withdrawn. */
  protected readonly confirmWithdraw = signal<BreachReport | null>(null);

  ngOnInit(): void {
    this.load();
    this.api.canaryRuns().subscribe({
      next: (runs) => this.leakyRuns.set(runs.filter((r) => r.status === 'COMPLETED' && (r.leak_rate ?? 0) > 0)),
      error: () => this.leakyRuns.set([]),
    });
    this.api.incidents(null, null).subscribe({
      next: (res) => this.exposures.set(res.items.filter((i) => i.incident_type === 'DATA_EXPOSURE')),
      error: () => this.exposures.set([]),
    });
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.breachReports().subscribe({
      next: (items) => {
        this.items.set(items);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
      },
    });
  }

  protected chooseSource(source: BreachReportSource): void {
    this.source.set(source);
    this.ref.set('');
    this.draftError.set(null);
  }

  protected canDraft(): boolean {
    return this.source() === 'window' ? !!(this.from() && this.to()) : !!this.ref();
  }

  protected draft(): void {
    const source = this.source();
    const body =
      source === 'window'
        ? { source, from: new Date(this.from()).toISOString(), to: new Date(this.to()).toISOString() }
        : { source, ref: this.ref() };
    this.drafting.set(true);
    this.draftError.set(null);
    this.api.draftBreachReport(body).subscribe({
      next: (report) => {
        this.drafting.set(false);
        this.items.update((items) => [report, ...items]);
        this.open(report);
        this.notify.success('Draft report created. Nothing was sent or filed.');
      },
      error: (err: ApiError) => {
        this.drafting.set(false);
        this.draftError.set(err);
      },
    });
  }

  protected open(report: BreachReport): void {
    this.selectedId.set(report.report_id);
    this.verify.set(null);
    this.actionError.set(null);
  }

  protected close(): void {
    // Escape first dismisses an open confirmation, not the drawer behind it.
    if (this.confirmWithdraw()) {
      this.confirmWithdraw.set(null);
      return;
    }
    this.selectedId.set(null);
  }

  protected runVerify(report: BreachReport): void {
    this.busy.set(true);
    this.api.verifyBreachReport(report.report_id).subscribe({
      next: (result) => {
        this.verify.set(result);
        this.busy.set(false);
      },
      error: (err: ApiError) => this.fail(err),
    });
  }

  protected review(report: BreachReport, decision: 'REVIEWED' | 'WITHDRAWN'): void {
    if (this.reviewer().trim().length < 2) {
      return;
    }
    this.busy.set(true);
    this.api.reviewBreachReport(report.report_id, this.reviewer().trim(), decision, '').subscribe({
      next: (updated) => this.replace(updated),
      error: (err: ApiError) => this.fail(err),
    });
  }

  protected createIncident(report: BreachReport): void {
    this.busy.set(true);
    this.api.breachReportIncident(report.report_id).subscribe({
      next: (updated) => {
        this.replace(updated);
        this.notify.success(`Incident ${updated.incident_id} opened and linked.`);
      },
      error: (err: ApiError) => this.fail(err),
    });
  }

  protected download(report: BreachReport): void {
    this.api.breachReportMarkdown(report.report_id).subscribe({
      next: (markdown) => {
        const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = `${report.report_id}-DRAFT.md`;
        link.click();
        URL.revokeObjectURL(url);
      },
      error: (err: ApiError) => this.actionError.set(err),
    });
  }

  protected runLabel(run: CanaryRunSummary): string {
    const leak = run.leak_rate === null ? '-' : `${(run.leak_rate * 100).toFixed(1)}%`;
    return `${new Date(run.created_at).toLocaleString()} - leak rate ${leak} (${run.run_id.slice(-6)})`;
  }

  private replace(updated: BreachReport): void {
    this.items.update((items) => items.map((r) => (r.report_id === updated.report_id ? updated : r)));
    this.busy.set(false);
  }

  private fail(err: ApiError): void {
    this.actionError.set(err);
    this.busy.set(false);
  }
}
