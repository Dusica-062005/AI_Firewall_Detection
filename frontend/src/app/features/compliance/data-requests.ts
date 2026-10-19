import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';

import {
  AiSystem,
  ApiError,
  DataRequest,
  DataRequestStatus,
  DataRequestSystem,
  DataRequestType,
  SystemTaskStatus,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';

/** "12 days left", "1 day left", "3 days overdue". */
export function formatDaysRemaining(days: number): string {
  const abs = Math.abs(days);
  const text = `${abs} ${abs === 1 ? 'day' : 'days'}`;
  return `${text} ${days < 0 ? 'overdue' : 'left'}`;
}

@Component({
  selector: 'app-data-requests',
  imports: [ReactiveFormsModule, DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './data-requests.html',
  styleUrl: './compliance.scss',
  host: { '(document:keydown.escape)': 'closeAll()' },
})
export class DataRequests implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  protected readonly items = signal<DataRequest[]>([]);
  protected readonly systems = signal<AiSystem[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly formError = signal<ApiError | null>(null);
  protected readonly saving = signal(false);

  protected readonly statusFilter = signal<DataRequestStatus | ''>('');
  protected readonly creating = signal(false);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly selected = computed(() => this.items().find((r) => r.request_id === this.selectedId()) ?? null);
  protected readonly visible = computed(() => {
    const status = this.statusFilter();
    return status ? this.items().filter((r) => r.status === status) : this.items();
  });
  /** Retired systems no longer hold new data, so they are not offered for new requests. */
  protected readonly activeSystems = computed(() => this.systems().filter((s) => s.status !== 'RETIRED'));

  protected readonly statuses: DataRequestStatus[] = ['OPEN', 'COMPLETED'];
  protected readonly types: DataRequestType[] = ['ERASURE', 'ACCESS'];
  protected readonly formatDays = formatDaysRemaining;

  protected readonly createForm = new FormGroup({
    request_type: new FormControl<DataRequestType>('ERASURE', { nonNullable: true }),
    subject_reference: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(3), Validators.maxLength(80)],
    }),
    system_ids: new FormControl<string[]>([], { nonNullable: true, validators: [Validators.required] }),
  });

  /** Per-system note being typed in the request drawer, keyed by system ID. */
  protected readonly notes = signal<Record<string, string>>({});

  ngOnInit(): void {
    this.load();
    this.api.aiSystems().subscribe({ next: (res) => this.systems.set(res.items), error: () => undefined });
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.dataRequests().subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.items.set([]);
        this.loading.set(false);
      },
    });
  }

  protected setStatus(value: string): void {
    this.statusFilter.set(value as DataRequestStatus | '');
  }

  protected deadlineLabel(r: DataRequest): string | null {
    return r.days_remaining === null ? null : formatDaysRemaining(r.days_remaining);
  }

  protected progress(r: DataRequest): number {
    return r.systems_total ? Math.round((r.systems_done / r.systems_total) * 100) : 0;
  }

  protected hasSystem(id: string): boolean {
    return this.createForm.controls.system_ids.value.includes(id);
  }

  protected toggleSystem(id: string, checked: boolean): void {
    const control = this.createForm.controls.system_ids;
    const current = control.value.filter((s) => s !== id);
    control.setValue(checked ? [...current, id] : current);
    control.markAsTouched();
  }

  protected selectAllSystems(): void {
    this.createForm.controls.system_ids.setValue(this.activeSystems().map((s) => s.system_id));
  }

  protected openCreate(): void {
    this.createForm.reset({ request_type: 'ERASURE', subject_reference: '', system_ids: [] });
    this.formError.set(null);
    this.creating.set(true);
  }

  protected open(request: DataRequest): void {
    this.selectedId.set(request.request_id);
    this.notes.set({});
    this.formError.set(null);
  }

  protected closeAll(): void {
    this.creating.set(false);
    this.selectedId.set(null);
  }

  protected setNote(systemId: string, value: string): void {
    this.notes.update((n) => ({ ...n, [systemId]: value }));
  }

  protected submitCreate(): void {
    this.createForm.markAllAsTouched();
    if (this.createForm.invalid || !this.createForm.controls.system_ids.value.length) {
      return;
    }
    const v = this.createForm.getRawValue();
    this.saving.set(true);
    this.formError.set(null);
    this.api
      .createDataRequest({ request_type: v.request_type, subject_reference: v.subject_reference.trim(), system_ids: v.system_ids })
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.creating.set(false);
          this.notify.success(`Request ${created.request_id} logged. Due ${new Date(created.due_at).toLocaleDateString()}.`);
          this.load();
        },
        error: (err: ApiError) => {
          this.saving.set(false);
          this.formError.set(err);
        },
      });
  }

  protected updateSystem(request: DataRequest, task: DataRequestSystem, status: SystemTaskStatus): void {
    this.saving.set(true);
    this.formError.set(null);
    this.api.updateDataRequestSystem(request.request_id, task.system_id, status, this.notes()[task.system_id] ?? task.note).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((r) => (r.request_id === updated.request_id ? updated : r)));
        this.saving.set(false);
        this.notify.success(
          updated.status === 'COMPLETED' ? `Request ${updated.request_id} completed.` : `${task.system_name} marked ${status.replace(/_/g, ' ').toLowerCase()}.`,
        );
      },
      error: (err: ApiError) => {
        this.saving.set(false);
        this.formError.set(err);
      },
    });
  }
}
