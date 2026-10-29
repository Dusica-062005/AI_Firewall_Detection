import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, effect, inject, input, signal } from '@angular/core';
import { AbstractControl, FormControl, FormGroup, ReactiveFormsModule, ValidationErrors } from '@angular/forms';
import { Router } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, AuditEvent, AuditFilters, Policy } from '../../core/models/api.models';
import { DisplayNamesService } from '../../core/services/display-names.service';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { DurationPipe, HumanizePipe } from '../../shared/pipes/format.pipes';

const PAGE_SIZE = 20;

/** "From" after "To" can never match anything, so the form says so instead of showing an empty table. */
function dateRangeValidator(group: AbstractControl): ValidationErrors | null {
  const { date_from, date_to } = group.value as { date_from?: string; date_to?: string };
  return date_from && date_to && new Date(date_from) > new Date(date_to) ? { dateRange: true } : null;
}

@Component({
  selector: 'app-audit',
  imports: [ReactiveFormsModule, DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, DurationPipe, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './audit.html',
  styleUrl: './audit.scss',
  host: { '(document:keydown.escape)': 'onEscape()' },
})
export class Audit implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly router = inject(Router);
  protected readonly names = inject(DisplayNamesService);

  /** Bound from the ?event= query parameter. */
  readonly event = input<string | undefined>();

  protected readonly items = signal<AuditEvent[]>([]);
  protected readonly total = signal(0);
  protected readonly page = signal(1);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly exporting = signal(false);
  protected readonly exportError = signal<ApiError | null>(null);

  /** Evidence export for an auditor: events in the From/To range (+ receipts and chain check in JSON). */
  protected exportRecords(format: 'json' | 'csv'): void {
    if (this.filters.hasError('dateRange')) {
      return;
    }
    const { date_from, date_to } = this.filters.getRawValue() as { date_from?: string; date_to?: string };
    const toIso = (value?: string) => (value ? new Date(value).toISOString() : undefined);
    this.exporting.set(true);
    this.exportError.set(null);
    this.api.auditExport(format, toIso(date_from), toIso(date_to)).subscribe({
      next: (content) => {
        const type = format === 'csv' ? 'text/csv' : 'application/json';
        const url = URL.createObjectURL(new Blob([content], { type }));
        const link = document.createElement('a');
        link.href = url;
        link.download = `audit-evidence-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.${format}`;
        link.click();
        URL.revokeObjectURL(url);
        this.exporting.set(false);
      },
      error: (err: ApiError) => {
        this.exportError.set(err);
        this.exporting.set(false);
      },
    });
  }
  protected readonly policies = signal<Policy[]>([]);

  protected readonly selected = signal<AuditEvent | null>(null);
  protected readonly detailError = signal<ApiError | null>(null);
  protected readonly detailLoading = signal(false);

  protected readonly pageCount = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly rangeText = computed(() => {
    if (!this.total()) {
      return '0 events';
    }
    const start = (this.page() - 1) * PAGE_SIZE + 1;
    return `${start}-${Math.min(this.page() * PAGE_SIZE, this.total())} of ${this.total()} events`;
  });

  protected readonly decisions = ['ALLOWED', 'REDACTED', 'LOCAL_ONLY', 'BLOCKED', 'PROCESSING_FAILED'];
  protected readonly statuses = ['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'FAILED'];
  protected readonly destinations = ['CLOUD', 'LOCAL', 'NONE'];

  protected readonly filters = new FormGroup({
    date_from: new FormControl('', { nonNullable: true }),
    date_to: new FormControl('', { nonNullable: true }),
    decision: new FormControl('', { nonNullable: true }),
    policy_id: new FormControl('', { nonNullable: true }),
    status: new FormControl('', { nonNullable: true }),
    destination: new FormControl('', { nonNullable: true }),
    request_id: new FormControl('', { nonNullable: true }),
  }, { validators: dateRangeValidator });

  constructor() {
    effect(() => {
      const id = this.event();
      if (id) {
        this.openById(id);
      } else {
        this.selected.set(null);
      }
    });
  }

  ngOnInit(): void {
    this.load(1);
    this.names.load();
    this.api.policies().subscribe({ next: (res) => this.policies.set(res.items), error: () => undefined });
  }

  protected apply(): void {
    if (this.filters.hasError('dateRange')) {
      return; // the template shows the reason next to the To field
    }
    this.load(1);
  }

  protected reset(): void {
    this.filters.reset();
    this.load(1);
  }

  protected load(page: number): void {
    const v = this.filters.getRawValue();
    const filters: AuditFilters = {
      decision: v.decision || null,
      policy_id: v.policy_id || null,
      status: v.status || null,
      destination: v.destination || null,
      request_id: v.request_id.trim() || null,
      date_from: v.date_from ? new Date(v.date_from).toISOString() : null,
      date_to: v.date_to ? new Date(v.date_to).toISOString() : null,
    };
    this.loading.set(true);
    this.error.set(null);
    this.api.audit(filters, page, PAGE_SIZE).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.total.set(res.total);
        this.page.set(res.page);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.items.set([]);
        this.total.set(0);
        this.loading.set(false);
      },
    });
  }

  protected open(event: AuditEvent): void {
    this.router.navigate([], { queryParams: { event: event.event_id }, queryParamsHandling: 'merge' });
  }

  protected onEscape(): void {
    if (this.event()) {
      this.close();
    }
  }

  protected close(): void {
    this.router.navigate([], { queryParams: { event: null }, queryParamsHandling: 'merge' });
  }

  private openById(id: string): void {
    this.detailLoading.set(true);
    this.detailError.set(null);
    this.api.auditEvent(id).subscribe({
      next: (ev) => {
        this.selected.set(ev);
        this.detailLoading.set(false);
      },
      error: (err: ApiError) => {
        this.selected.set(null);
        this.detailError.set(err);
        this.detailLoading.set(false);
      },
    });
  }

  protected categories(ev: AuditEvent): string[] {
    return Object.keys(ev.entity_counts);
  }

  protected stageRows(ev: AuditEvent): { label: string; value: number | null }[] {
    const l = ev.latency_ms;
    return [
      { label: 'Detection', value: l['detection_ms'] ?? null },
      { label: 'Policy evaluation', value: l['policy_ms'] ?? null },
      { label: 'Protection', value: l['protection_ms'] ?? null },
      { label: 'Local AI inference', value: l['local_ai_ms'] ?? null },
      { label: 'Outbound validation', value: l['validation_ms'] ?? null },
      { label: 'Cloud handoff', value: l['cloud_ms'] ?? null },
    ];
  }
}
