import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { humanize } from '../pipes/format.pipes';

type Variant = 'success' | 'warning' | 'error' | 'info' | 'local' | 'neutral';

interface BadgeStyle {
  variant: Variant;
  icon: string;
}

// One mapping for every status vocabulary used by the backend, so colours stay consistent.
const STYLES: Record<string, BadgeStyle> = {
  // Decisions
  ALLOWED: { variant: 'success', icon: 'circle-check' },
  REDACTED: { variant: 'info', icon: 'eye-off' },
  LOCAL_ONLY: { variant: 'local', icon: 'hard-drive' },
  BLOCKED: { variant: 'error', icon: 'shield-ban' },
  PROCESSING_FAILED: { variant: 'warning', icon: 'triangle-alert' },
  // Policy actions
  ALLOW: { variant: 'success', icon: 'circle-check' },
  REDACT: { variant: 'info', icon: 'eye-off' },
  BLOCK: { variant: 'error', icon: 'shield-ban' },
  UNRESOLVED: { variant: 'warning', icon: 'triangle-alert' },
  // Processing / step status
  COMPLETED: { variant: 'success', icon: 'circle-check' },
  COMPLETED_WITH_WARNINGS: { variant: 'warning', icon: 'triangle-alert' },
  FAILED: { variant: 'error', icon: 'circle-x' },
  SKIPPED: { variant: 'neutral', icon: 'circle-minus' },
  WARNING: { variant: 'warning', icon: 'triangle-alert' },
  PENDING: { variant: 'neutral', icon: 'circle-dashed' },
  // Destinations
  CLOUD: { variant: 'info', icon: 'cloud' },
  LOCAL: { variant: 'local', icon: 'hard-drive' },
  NONE: { variant: 'neutral', icon: 'ban' },
  // Integrations and components
  CONNECTED: { variant: 'success', icon: 'circle-check' },
  READY: { variant: 'success', icon: 'circle-check' },
  OK: { variant: 'success', icon: 'circle-check' },
  DEGRADED: { variant: 'warning', icon: 'triangle-alert' },
  MODEL_MISSING: { variant: 'warning', icon: 'triangle-alert' },
  UNREACHABLE: { variant: 'error', icon: 'circle-x' },
  UNAVAILABLE: { variant: 'error', icon: 'circle-x' },
  ERROR: { variant: 'error', icon: 'circle-x' },
  NOT_LOADED: { variant: 'neutral', icon: 'circle-dashed' },
  // Local AI / outbound
  GENERATED: { variant: 'success', icon: 'circle-check' },
  SENT: { variant: 'success', icon: 'send' },
  NOT_AUTHORIZED: { variant: 'neutral', icon: 'lock' },
  SKIPPED_BY_MODE: { variant: 'neutral', icon: 'circle-minus' },
  VALIDATION_FAILED: { variant: 'error', icon: 'shield-alert' },
  REJECTED: { variant: 'error', icon: 'circle-x' },
  TIMEOUT: { variant: 'warning', icon: 'clock' },
  INVALID_OUTPUT: { variant: 'warning', icon: 'triangle-alert' },
  ENABLED: { variant: 'success', icon: 'circle-check' },
  DISABLED: { variant: 'neutral', icon: 'circle-minus' },
  // Router, kill switch and round trip
  KILL_SWITCH: { variant: 'error', icon: 'power' },
  HELD_LOCAL: { variant: 'local', icon: 'hard-drive' },
  ACTIVE: { variant: 'success', icon: 'cloud' },
  REHYDRATED: { variant: 'success', icon: 'key-round' },
  TOKENS_ONLY: { variant: 'warning', icon: 'key-round' },
  NO_SUMMARY: { variant: 'neutral', icon: 'circle-minus' },
  // Trust-layer keys and receipts
  CONFIGURED: { variant: 'success', icon: 'key-round' },
  NOT_CONFIGURED: { variant: 'warning', icon: 'key-round' },
  INVALID: { variant: 'error', icon: 'key-round' },
  SIGNED: { variant: 'success', icon: 'fingerprint' },
  UNSIGNED: { variant: 'warning', icon: 'fingerprint' },
  CHAIN_OK: { variant: 'success', icon: 'link' },
  TAMPERED: { variant: 'error', icon: 'shield-alert' },
  // Measurement runs
  RUNNING: { variant: 'info', icon: 'timer' },
  // Compliance controls
  PASS: { variant: 'success', icon: 'circle-check' },
  PARTIAL: { variant: 'warning', icon: 'triangle-alert' },
  FAIL: { variant: 'error', icon: 'circle-x' },
  // AI systems
  APPROVED: { variant: 'success', icon: 'circle-check' },
  UNDER_REVIEW: { variant: 'warning', icon: 'clock' },
  RETIRED: { variant: 'neutral', icon: 'circle-minus' },
  OVERDUE: { variant: 'error', icon: 'clock' },
  // Incidents
  CRITICAL: { variant: 'error', icon: 'shield-alert' },
  HIGH: { variant: 'warning', icon: 'triangle-alert' },
  MEDIUM: { variant: 'info', icon: 'circle-dot' },
  LOW: { variant: 'neutral', icon: 'circle-dot' },
  REPORTED: { variant: 'warning', icon: 'flag' },
  CONTAINED: { variant: 'info', icon: 'shield-check' },
  ROOT_CAUSE_IDENTIFIED: { variant: 'local', icon: 'search' },
  CLOSED: { variant: 'success', icon: 'circle-check' },
  ON_TRACK: { variant: 'success', icon: 'timer' },
  AT_RISK: { variant: 'warning', icon: 'timer' },
  BREACHED: { variant: 'error', icon: 'timer' },
  MET: { variant: 'success', icon: 'circle-check' },
  MISSED: { variant: 'error', icon: 'circle-x' },
  // Data-subject requests
  OPEN: { variant: 'warning', icon: 'clock' },
  DONE: { variant: 'success', icon: 'circle-check' },
  NOT_HELD: { variant: 'neutral', icon: 'circle-minus' },
  ERASURE: { variant: 'info', icon: 'eraser' },
  ACCESS: { variant: 'local', icon: 'file-search' },
};

const LABELS: Record<string, string> = {
  LOCAL_ONLY: 'Local only',
  PROCESSING_FAILED: 'Processing failed',
  NOT_AUTHORIZED: 'Not authorized',
  SKIPPED_BY_MODE: 'Skipped by mode',
  MODEL_MISSING: 'Model missing',
  KILL_SWITCH: 'Kill switch',
  HELD_LOCAL: 'Held local',
  TOKENS_ONLY: 'Tokens only',
  NO_SUMMARY: 'No summary',
  NOT_CONFIGURED: 'Not configured',
  CHAIN_OK: 'Chain OK',
};

@Component({
  selector: 'app-status-badge',
  imports: [LucideDynamicIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="badge badge-{{ style().variant }}" [class.badge--strong]="strong()">
      <svg class="icon" [lucideIcon]="style().icon" aria-hidden="true"></svg>
      <span>{{ text() }}</span>
    </span>
  `,
  styles: `
    :host {
      display: inline-flex;
    }
    .badge--strong {
      height: 26px;
      padding: 0 10px;
      font-size: 13px;
      letter-spacing: 0.02em;
    }
  `,
})
export class StatusBadge {
  readonly value = input.required<string | null | undefined>();
  readonly label = input<string | null>(null);
  readonly uppercase = input(false);
  readonly strong = input(false);

  protected readonly style = computed<BadgeStyle>(
    () => STYLES[(this.value() ?? '').toUpperCase()] ?? { variant: 'neutral', icon: 'circle-dot' },
  );

  protected readonly text = computed(() => {
    const raw = (this.value() ?? 'Unknown').toString();
    const label = this.label() ?? LABELS[raw.toUpperCase()] ?? humanize(raw);
    return this.uppercase() ? raw.replace(/_/g, ' ').toUpperCase() : label;
  });
}
