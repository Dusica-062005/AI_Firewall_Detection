import { DecimalPipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, AuditEvent, FirewallResult } from '../../core/models/api.models';
import { DisplayNamesService } from '../../core/services/display-names.service';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { DurationPipe, HumanizePipe } from '../../shared/pipes/format.pipes';
import { HighlightedText } from './highlighted-text';
import { InspectorDecision } from './inspector-decision';
import { ProcessingSteps } from './processing-steps';

type Tab = 'summary' | 'cloud' | 'policy' | 'audit';

@Component({
  selector: 'app-inspector-result',
  imports: [
    RouterLink, LucideDynamicIcon, DecimalPipe, JsonPipe, StatusBadge, ErrorAlert, DurationPipe, HumanizePipe,
    HighlightedText, InspectorDecision, ProcessingSteps,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './inspector-result.html',
  styleUrl: './inspector-result.scss',
})
export class InspectorResult {
  private readonly api = inject(FirewallApiService);
  protected readonly names = inject(DisplayNamesService);

  readonly result = input.required<FirewallResult>();
  readonly original = input.required<string>();

  protected readonly tab = signal<Tab>('summary');
  protected readonly expandedEntity = signal<number | null>(null);
  protected readonly auditEvent = signal<AuditEvent | null>(null);
  protected readonly auditError = signal<ApiError | null>(null);
  protected readonly failedChecks = computed(() => this.result().outbound.validation.filter((c) => !c.passed).length);

  protected readonly routeLabel = computed(() => {
    const route = this.result().routing?.route;
    return route === 'CLOUD' ? 'Routed to cloud stand-in' : route === 'LOCAL' ? 'Kept local' : 'Not processed';
  });

  /** Left side of the round trip: exactly what left the firewall, or what the local model read. */
  protected readonly machineTitle = computed(() => {
    const r = this.result();
    if (r.outbound.reached_receiver) {
      return 'What the cloud saw (exact payload sent to mock CloudLink)';
    }
    return r.summary.status === 'GENERATED' ? 'What the local model saw (nothing left the firewall)' : 'Protected text (nothing left the firewall)';
  });

  protected readonly machineText = computed<string | null>(() => {
    const r = this.result();
    const sent = r.outbound.payload?.['sanitized_transcript'];
    if (r.outbound.reached_receiver && typeof sent === 'string') {
      return sent;
    }
    return r.decision === 'BLOCKED' ? null : r.redacted_transcript;
  });

  constructor() {
    this.names.load();
    effect(() => {
      const r = this.result();
      this.auditEvent.set(null);
      this.auditError.set(null);
      this.tab.set(r.operation === 'INSPECT' ? 'policy' : 'summary');
      if (r.event_id) {
        this.api.auditEvent(r.event_id).subscribe({
          next: (event) => this.auditEvent.set(event),
          error: (err: ApiError) => this.auditError.set(err),
        });
      }
    });
  }

  protected toggleEntity(index: number): void {
    this.expandedEntity.update((current) => (current === index ? null : index));
  }

  protected select(tab: Tab): void {
    this.tab.set(tab);
  }

  protected onTabKey(event: KeyboardEvent): void {
    const order: Tab[] = ['summary', 'cloud', 'policy', 'audit'];
    const index = order.indexOf(this.tab());
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const next = order[(index + (event.key === 'ArrowRight' ? 1 : order.length - 1)) % order.length];
      this.tab.set(next);
      (document.getElementById(`tab-${next}`) as HTMLElement | null)?.focus();
    }
  }

  protected latencyRows(): { label: string; value: number | null }[] {
    const l = this.result().latency;
    return [
      { label: 'Detection', value: l.detection_ms },
      { label: 'Policy evaluation', value: l.policy_ms },
      { label: 'Protection (redaction)', value: l.protection_ms },
      { label: 'Local AI inference', value: l.local_ai_ms },
      { label: 'Outbound validation', value: l.validation_ms },
      { label: 'Cloud handoff', value: l.cloud_ms },
      { label: 'Audit write', value: l.audit_ms },
    ];
  }

  protected objectKeys(record: Record<string, unknown>): string[] {
    return Object.keys(record);
  }
}
