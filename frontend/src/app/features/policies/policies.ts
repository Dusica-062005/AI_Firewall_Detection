import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { Observable } from 'rxjs';

import { ApiError, Policy, PolicyAction, PolicyDefinition, ProfileInfo } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ConfirmDialog } from '../../shared/components/confirm-dialog';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { PolicyEditor } from './policy-editor';

type Confirm = { kind: 'delete'; policy: Policy } | { kind: 'reset' };

@Component({
  selector: 'app-policies',
  imports: [FormsModule, DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, ConfirmDialog, PolicyEditor],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './policies.html',
  styleUrl: './policies.scss',
})
export class Policies implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  protected readonly policies = signal<Policy[]>([]);
  protected readonly policyVersion = signal<string>('');
  protected readonly categories = signal<string[]>([]);
  protected readonly profiles = signal<ProfileInfo[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly busyId = signal<string | null>(null);

  protected readonly editing = signal<Policy | null | undefined>(undefined); // undefined = closed, null = new
  protected readonly expanded = signal<string | null>(null);
  protected readonly confirm = signal<Confirm | null>(null);
  protected readonly confirmBusy = signal(false);

  protected readonly search = signal('');
  protected readonly actionFilter = signal<PolicyAction | ''>('');
  protected readonly profileFilter = signal('');
  protected readonly actions: PolicyAction[] = ['ALLOW', 'REDACT', 'LOCAL_ONLY', 'BLOCK'];

  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    const action = this.actionFilter();
    const profile = this.profileFilter();
    return this.policies().filter(
      (p) =>
        (!q || p.name.toLowerCase().includes(q) || p.policy_id.includes(q) || p.entity_categories.some((c) => c.toLowerCase().includes(q))) &&
        (!action || p.action === action) &&
        (!profile || p.conditions.profiles.length === 0 || p.conditions.profiles.includes(profile)),
    );
  });

  protected readonly enabledCount = computed(() => this.policies().filter((p) => p.enabled).length);

  ngOnInit(): void {
    this.load();
    this.api.entityCategories().subscribe({ next: (res) => this.categories.set(res.items), error: () => this.categories.set([]) });
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.policies().subscribe({
      next: (res) => {
        this.policies.set(res.items);
        this.policyVersion.set(res.policy_version);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
      },
    });
    this.api.profiles().subscribe({ next: (res) => this.profiles.set(res.items), error: () => undefined });
  }

  protected toggleRow(id: string): void {
    this.expanded.update((current) => (current === id ? null : id));
  }

  protected clearFilters(): void {
    this.search.set('');
    this.actionFilter.set('');
    this.profileFilter.set('');
  }

  protected conditionsText(p: Policy): string {
    const profiles = p.conditions.profiles.length ? p.conditions.profiles.join(', ') : 'All profiles';
    const channels = p.conditions.channels.length ? p.conditions.channels.join(', ') : 'all channels';
    const conf = p.conditions.min_confidence > 0 ? `, score >= ${p.conditions.min_confidence}` : '';
    return `${profiles}; ${channels}${conf}`;
  }

  protected toggleEnabled(policy: Policy, checkbox: HTMLInputElement): void {
    const enabled = checkbox.checked;
    this.busyId.set(policy.policy_id);
    const body: PolicyDefinition = {
      name: policy.name,
      description: policy.description,
      enabled,
      priority: policy.priority,
      entity_categories: policy.entity_categories,
      action: policy.action,
      destination: policy.destination,
      conditions: policy.conditions,
    };
    this.api.updatePolicy(policy.policy_id, body).subscribe({
      next: (updated) => {
        this.replace(updated);
        this.busyId.set(null);
        this.notify.success(`${updated.name} ${updated.enabled ? 'enabled' : 'disabled'}.`);
        this.refreshVersion();
      },
      error: (err: ApiError) => {
        this.busyId.set(null);
        checkbox.checked = policy.enabled; // revert to the stored state
        this.notify.error(this.adminHint(err));
      },
    });
  }

  protected onSaved(policy: Policy): void {
    const exists = this.policies().some((p) => p.policy_id === policy.policy_id);
    this.editing.set(undefined);
    this.notify.success(exists ? `Policy ${policy.name} saved.` : `Policy ${policy.name} created.`);
    this.load();
  }

  protected runConfirm(): void {
    const c = this.confirm();
    if (!c) {
      return;
    }
    this.confirmBusy.set(true);
    const request$: Observable<unknown> =
      c.kind === 'delete' ? this.api.deletePolicy(c.policy.policy_id) : this.api.resetPolicies();
    request$.subscribe({
      next: () => {
        this.confirmBusy.set(false);
        this.confirm.set(null);
        this.notify.success(c.kind === 'delete' ? `Policy ${c.policy.name} deleted.` : 'Policies reset to the default configuration.');
        this.load();
      },
      error: (err: ApiError) => {
        this.confirmBusy.set(false);
        this.confirm.set(null);
        this.notify.error(this.adminHint(err));
      },
    });
  }

  private replace(updated: Policy): void {
    this.policies.update((list) => list.map((p) => (p.policy_id === updated.policy_id ? updated : p)));
  }

  private refreshVersion(): void {
    this.api.policies().subscribe({ next: (res) => this.policyVersion.set(res.policy_version), error: () => undefined });
  }

  private adminHint(err: ApiError): string {
    return err.status === 401 ? `${err.message} Enter the administrator key in Settings.` : err.message;
  }
}
