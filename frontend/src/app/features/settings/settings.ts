import { DatePipe, DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, AppConfig, HealthResponse, IntegrationsStatus } from '../../core/models/api.models';
import { AdminKeyService } from '../../core/services/admin-key.service';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { RuntimeConfigService } from '../../core/services/runtime-config.service';
import { SystemStatusService } from '../../core/services/system-status.service';
import { ConfirmDialog } from '../../shared/components/confirm-dialog';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { BytesPipe, DurationPipe, HumanizePipe } from '../../shared/pipes/format.pipes';

const COMPONENT_LABELS: Record<string, string> = {
  database: 'Database (SQLite)',
  detection: 'Detection engine (Presidio)',
  policies: 'Policy configuration',
  ollama: 'Local model (Ollama)',
  cloudlink: 'CloudLink receiver (mock)',
};

@Component({
  selector: 'app-settings',
  imports: [FormsModule, DatePipe, DecimalPipe, NgTemplateOutlet, LucideDynamicIcon, StatusBadge, ErrorAlert, ConfirmDialog, BytesPipe, DurationPipe, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './settings.html',
  styleUrl: './settings.scss',
})
export class Settings implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);
  private readonly system = inject(SystemStatusService);
  protected readonly admin = inject(AdminKeyService);
  protected readonly runtime = inject(RuntimeConfigService);

  protected readonly config = signal<AppConfig | null>(null);
  protected readonly health = signal<HealthResponse | null>(null);
  protected readonly healthLoading = signal(false);
  protected readonly healthError = signal<ApiError | null>(null);
  protected readonly integrations = signal<IntegrationsStatus | null>(null);
  /** Set when the integration check itself failed, so a failure is never shown as "not checked". */
  protected readonly integrationsError = signal<ApiError | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly loading = signal(true);
  protected readonly testing = signal(false);
  protected readonly confirmPurge = signal(false);
  protected readonly purging = signal(false);
  protected adminKeyInput = '';
  protected readonly componentLabels = COMPONENT_LABELS;

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.appConfig().subscribe({
      next: (config) => {
        this.config.set(config);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
      },
    });
    this.loadHealth();
    this.testIntegrations();
  }

  protected loadHealth(): void {
    this.healthLoading.set(true);
    this.api.health().subscribe({
      next: (h) => {
        this.health.set(h);
        this.healthError.set(null);
        this.healthLoading.set(false);
      },
      error: (err: ApiError) => {
        this.health.set(null);
        this.healthError.set(err);
        this.healthLoading.set(false);
      },
    });
    this.system.refresh();
  }

  protected testIntegrations(): void {
    this.testing.set(true);
    this.api.integrations().subscribe({
      next: (status) => {
        this.integrations.set(status);
        this.integrationsError.set(null);
        this.testing.set(false);
      },
      error: (err: ApiError) => {
        this.integrations.set(null);
        this.integrationsError.set(err);
        this.testing.set(false);
        this.notify.error(err.message);
      },
    });
  }

  protected componentKeys(h: HealthResponse): string[] {
    return Object.keys(h.components);
  }

  protected saveAdminKey(): void {
    this.admin.set(this.adminKeyInput);
    this.adminKeyInput = '';
    this.notify.success(this.admin.hasKey() ? 'Administrator key stored for this browser session.' : 'Administrator key cleared.');
  }

  protected clearAdminKey(): void {
    this.admin.set('');
    this.notify.success('Administrator key cleared.');
  }

  protected purge(): void {
    this.purging.set(true);
    this.api.purgeAudit().subscribe({
      next: (res) => {
        this.purging.set(false);
        this.confirmPurge.set(false);
        this.notify.success(`Retention applied. ${res.deleted} event(s) older than ${res.retention_days} days removed.`);
        this.load();
      },
      error: (err: ApiError) => {
        this.purging.set(false);
        this.confirmPurge.set(false);
        this.notify.error(err.status === 401 ? `${err.message} Enter the administrator key below.` : err.message);
      },
    });
  }
}
