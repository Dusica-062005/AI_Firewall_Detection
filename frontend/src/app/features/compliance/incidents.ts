import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';

import {
  AiSystem,
  ApiError,
  Incident,
  IncidentStatus,
  IncidentType,
  Severity,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ConfirmDialog } from '../../shared/components/confirm-dialog';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';

const STAGES: IncidentStatus[] = ['REPORTED', 'CONTAINED', 'ROOT_CAUSE_IDENTIFIED', 'CLOSED'];

/** "5h 12m left", "2d 3h overdue". */
export function formatSla(seconds: number): string {
  const abs = Math.abs(seconds);
  const days = Math.floor(abs / 86400);
  const hours = Math.floor((abs % 86400) / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const text = days > 0 ? `${days}d ${hours}h` : hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  return `${text} ${seconds < 0 ? 'overdue' : 'left'}`;
}

@Component({
  selector: 'app-incidents',
  imports: [ReactiveFormsModule, DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, ConfirmDialog, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './incidents.html',
  styleUrl: './compliance.scss',
  host: { '(document:keydown.escape)': 'closeAll()' },
})
export class Incidents implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  protected readonly items = signal<Incident[]>([]);
  protected readonly systems = signal<AiSystem[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly formError = signal<ApiError | null>(null);
  protected readonly saving = signal(false);

  protected readonly statusFilter = signal<IncidentStatus | ''>('');
  protected readonly severityFilter = signal<Severity | ''>('');
  protected readonly creating = signal(false);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly selected = computed(() => this.items().find((i) => i.incident_id === this.selectedId()) ?? null);
  /** The incident awaiting confirmation before it is closed; closing cannot be undone. */
  protected readonly confirmClose = signal<Incident | null>(null);

  protected readonly statuses = STAGES;
  protected readonly severities: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
  protected readonly types: IncidentType[] = ['WRONG_ANSWER', 'DATA_EXPOSURE', 'BIASED_OUTPUT', 'POLICY_BYPASS', 'OTHER'];
  protected readonly formatSla = formatSla;

  protected readonly createForm = new FormGroup({
    title: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.minLength(3), Validators.maxLength(120)] }),
    description: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(2000)] }),
    incident_type: new FormControl<IncidentType>('WRONG_ANSWER', { nonNullable: true }),
    severity: new FormControl<Severity>('MEDIUM', { nonNullable: true }),
    owner: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(80)] }),
    ai_system_id: new FormControl('', { nonNullable: true }),
    related_event_id: new FormControl('', { nonNullable: true, validators: [Validators.pattern(/^(evt-[a-f0-9]{16})?$/)] }),
  });

  protected readonly stepForm = new FormGroup({
    note: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(500)] }),
    text: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(1000)] }),
  });

  protected readonly assignForm = new FormGroup({
    owner: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(80)] }),
    severity: new FormControl<Severity>('MEDIUM', { nonNullable: true }),
  });

  ngOnInit(): void {
    this.load();
    this.api.aiSystems().subscribe({ next: (res) => this.systems.set(res.items), error: () => undefined });
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.incidents(this.statusFilter() || null, this.severityFilter() || null).subscribe({
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
    this.statusFilter.set(value as IncidentStatus | '');
    this.load();
  }

  protected setSeverity(value: string): void {
    this.severityFilter.set(value as Severity | '');
    this.load();
  }

  protected systemName(id: string | null): string {
    return this.systems().find((s) => s.system_id === id)?.name ?? '-';
  }

  protected slaLabel(i: Incident): string | null {
    return i.sla_seconds_remaining === null ? null : formatSla(i.sla_seconds_remaining);
  }

  /** The stage an incident moves to next, or null when closed. */
  protected nextStage(i: Incident): IncidentStatus | null {
    return STAGES[STAGES.indexOf(i.status) + 1] ?? null;
  }

  protected stepLabel(stage: IncidentStatus | null): string {
    return (
      { CONTAINED: 'Mark as contained', ROOT_CAUSE_IDENTIFIED: 'Record root cause', CLOSED: 'Close incident' } as Record<string, string>
    )[stage ?? ''] ?? '';
  }

  protected openCreate(): void {
    this.createForm.reset({ incident_type: 'WRONG_ANSWER', severity: 'MEDIUM' });
    this.formError.set(null);
    this.creating.set(true);
  }

  protected open(incident: Incident): void {
    this.selectedId.set(incident.incident_id);
    this.stepForm.reset();
    this.assignForm.reset({ owner: incident.owner ?? '', severity: incident.severity });
    this.formError.set(null);
  }

  protected closeAll(): void {
    // Escape first dismisses an open confirmation, not the drawer behind it.
    if (this.confirmClose()) {
      this.confirmClose.set(null);
      return;
    }
    this.creating.set(false);
    this.selectedId.set(null);
  }

  protected submitCreate(): void {
    this.createForm.markAllAsTouched();
    if (this.createForm.invalid) {
      return;
    }
    const v = this.createForm.getRawValue();
    this.saving.set(true);
    this.formError.set(null);
    this.api
      .createIncident({
        title: v.title,
        description: v.description,
        incident_type: v.incident_type,
        severity: v.severity,
        owner: v.owner.trim() || null,
        ai_system_id: v.ai_system_id || null,
        related_event_id: v.related_event_id.trim() || null,
      })
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.creating.set(false);
          this.notify.success(`Incident ${created.incident_id} reported.`);
          this.load();
        },
        error: (err: ApiError) => {
          this.saving.set(false);
          this.formError.set(err);
        },
      });
  }

  protected advance(incident: Incident, confirmed = false): void {
    const stage = this.nextStage(incident);
    const { note, text } = this.stepForm.getRawValue();
    if (!stage) {
      return;
    }
    if ((stage === 'ROOT_CAUSE_IDENTIFIED' || stage === 'CLOSED') && !text.trim()) {
      this.stepForm.controls.text.markAsTouched();
      return;
    }
    if (stage === 'CLOSED' && !confirmed) {
      this.confirmClose.set(incident);
      return;
    }
    this.confirmClose.set(null);
    this.saving.set(true);
    this.formError.set(null);
    this.api
      .advanceIncident(incident.incident_id, {
        note,
        root_cause: stage === 'ROOT_CAUSE_IDENTIFIED' ? text : null,
        resolution: stage === 'CLOSED' ? text : null,
      })
      .subscribe({
        next: (updated) => {
          this.replace(updated);
          this.stepForm.reset();
          this.saving.set(false);
          this.notify.success(`Incident moved to ${updated.status.replace(/_/g, ' ').toLowerCase()}.`);
        },
        error: (err: ApiError) => {
          this.saving.set(false);
          this.formError.set(err);
        },
      });
  }

  protected saveAssignment(incident: Incident): void {
    const { owner, severity } = this.assignForm.getRawValue();
    const body: { owner?: string; severity?: Severity } = {};
    if (owner.trim() !== (incident.owner ?? '')) {
      body.owner = owner.trim();
    }
    if (severity !== incident.severity) {
      body.severity = severity;
    }
    if (!Object.keys(body).length) {
      return;
    }
    this.saving.set(true);
    this.formError.set(null);
    this.api.updateIncident(incident.incident_id, body).subscribe({
      next: (updated) => {
        this.replace(updated);
        this.saving.set(false);
        this.notify.success('Incident updated.');
      },
      error: (err: ApiError) => {
        this.saving.set(false);
        this.formError.set(err);
      },
    });
  }

  private replace(updated: Incident): void {
    this.items.update((list) => list.map((i) => (i.incident_id === updated.incident_id ? updated : i)));
    if (!this.items().some((i) => i.incident_id === updated.incident_id)) {
      this.load();
    }
  }
}
