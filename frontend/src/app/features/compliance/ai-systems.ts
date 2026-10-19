import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';

import { AiSystem, ApiError, Hosting, SystemStatus } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';

@Component({
  selector: 'app-ai-systems',
  imports: [ReactiveFormsModule, DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ai-systems.html',
  styleUrl: './compliance.scss',
  host: { '(document:keydown.escape)': 'closeAll()' },
})
export class AiSystems implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  protected readonly items = signal<AiSystem[]>([]);
  protected readonly categories = signal<string[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly formError = signal<ApiError | null>(null);
  protected readonly saving = signal(false);

  protected readonly creating = signal(false);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly selected = computed(() => this.items().find((s) => s.system_id === this.selectedId()) ?? null);
  protected readonly overdueCount = computed(() => this.items().filter((s) => s.review_overdue).length);

  protected readonly statuses: SystemStatus[] = ['APPROVED', 'UNDER_REVIEW', 'RETIRED'];
  protected readonly hostings: Hosting[] = ['LOCAL', 'CLOUD'];

  protected readonly createForm = new FormGroup({
    name: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.minLength(3), Validators.maxLength(80)] }),
    owner: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.minLength(2), Validators.maxLength(80)] }),
    purpose: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.minLength(3), Validators.maxLength(300)] }),
    hosting: new FormControl<Hosting>('CLOUD', { nonNullable: true }),
    status: new FormControl<SystemStatus>('UNDER_REVIEW', { nonNullable: true }),
    review_interval_days: new FormControl(180, { nonNullable: true, validators: [Validators.required, Validators.min(30), Validators.max(730)] }),
    data_categories: new FormControl<string[]>([], { nonNullable: true }),
  });

  protected readonly reviewStatus = new FormControl<SystemStatus | ''>('', { nonNullable: true });

  ngOnInit(): void {
    this.load();
    this.api.entityCategories().subscribe({ next: (res) => this.categories.set(res.items), error: () => undefined });
  }

  protected load(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.aiSystems().subscribe({
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

  protected hasCategory(category: string): boolean {
    return this.createForm.controls.data_categories.value.includes(category);
  }

  protected toggleCategory(category: string, checked: boolean): void {
    const current = this.createForm.controls.data_categories.value.filter((c) => c !== category);
    this.createForm.controls.data_categories.setValue(checked ? [...current, category] : current);
  }

  protected openCreate(): void {
    this.createForm.reset({ hosting: 'CLOUD', status: 'UNDER_REVIEW', review_interval_days: 180, data_categories: [] });
    this.formError.set(null);
    this.creating.set(true);
  }

  protected open(system: AiSystem): void {
    this.selectedId.set(system.system_id);
    this.reviewStatus.setValue('');
    this.formError.set(null);
  }

  protected closeAll(): void {
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
      .createAiSystem({
        name: v.name.trim(),
        owner: v.owner.trim(),
        purpose: v.purpose.trim(),
        hosting: v.hosting,
        status: v.status,
        review_interval_days: Number(v.review_interval_days),
        data_categories: v.data_categories,
      })
      .subscribe({
        next: (created) => {
          this.saving.set(false);
          this.creating.set(false);
          this.notify.success(`${created.name} added to the AI system register.`);
          this.load();
        },
        error: (err: ApiError) => {
          this.saving.set(false);
          this.formError.set(err);
        },
      });
  }

  protected markReviewed(system: AiSystem): void {
    this.saving.set(true);
    this.formError.set(null);
    this.api.reviewAiSystem(system.system_id, this.reviewStatus.value || null).subscribe({
      next: (updated) => {
        this.items.update((list) => list.map((s) => (s.system_id === updated.system_id ? updated : s)));
        this.reviewStatus.setValue('');
        this.saving.set(false);
        this.notify.success(`Review recorded for ${updated.name}.`);
      },
      error: (err: ApiError) => {
        this.saving.set(false);
        this.formError.set(err);
      },
    });
  }
}
