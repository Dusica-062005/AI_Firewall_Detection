import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';
import { forkJoin } from 'rxjs';

import {
  ApiError,
  AuditEvent,
  BenchmarkRun,
  CanaryRunSummary,
  IntegrationsStatus,
  MetricsSummary,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { SystemStatusService } from '../../core/services/system-status.service';
import { DecisionChart } from '../../shared/components/decision-chart';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { DurationPipe, HumanizePipe } from '../../shared/pipes/format.pipes';
import { pct } from '../measurements/measurement-format';

@Component({
  selector: 'app-overview',
  imports: [RouterLink, LucideDynamicIcon, DatePipe, DecimalPipe, DecisionChart, ErrorAlert, StatusBadge, DurationPipe, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './overview.html',
  styleUrl: './overview.scss',
})
export class Overview implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly router = inject(Router);
  protected readonly system = inject(SystemStatusService);

  protected readonly metrics = signal<MetricsSummary | null>(null);
  protected readonly recent = signal<AuditEvent[]>([]);
  protected readonly integrations = signal<IntegrationsStatus | null>(null);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly integrationsError = signal<ApiError | null>(null);

  protected readonly topCategories = computed(() => {
    const counts = this.metrics()?.entity_category_counts ?? {};
    return Object.entries(counts).slice(0, 4);
  });

  protected readonly hasActivity = computed(() => (this.metrics()?.total_requests ?? 0) > 0);

  /** Latest completed leak-canary run (Feature 5); null means not measured yet. */
  protected readonly lastCanary = signal<CanaryRunSummary | null>(null);
  protected readonly canaryError = signal<ApiError | null>(null);
  /** NFR-2 verdict of the latest completed benchmark; null means not measured yet. */
  protected readonly benchmark = signal<BenchmarkRun | null>(null);
  protected readonly pct = pct;

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      metrics: this.api.metrics(24),
      audit: this.api.audit({}, 1, 8),
    }).subscribe({
      next: ({ metrics, audit }) => {
        this.metrics.set(metrics);
        this.recent.set(audit.items);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.metrics.set(null);
        this.recent.set([]);
        this.loading.set(false);
      },
    });
    this.api.integrations().subscribe({
      next: (status) => {
        this.integrations.set(status);
        this.integrationsError.set(null);
      },
      error: (err: ApiError) => {
        this.integrations.set(null);
        this.integrationsError.set(err);
      },
    });
    this.api.canaryRuns().subscribe({
      next: (runs) => {
        this.lastCanary.set(runs.find((r) => r.status === 'COMPLETED') ?? null);
        this.canaryError.set(null);
      },
      error: (err: ApiError) => {
        this.lastCanary.set(null);
        this.canaryError.set(err);
      },
    });
    this.api.benchmarkLatest().subscribe({
      next: (latest) => this.benchmark.set(latest.completed),
      error: () => this.benchmark.set(null),
    });
    this.system.refresh();
  }

  protected openEvent(event: AuditEvent): void {
    this.router.navigate(['/audit'], { queryParams: { event: event.event_id } });
  }

  protected categories(event: AuditEvent): string[] {
    return Object.keys(event.entity_counts);
  }
}
