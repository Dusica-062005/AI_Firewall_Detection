import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { AbstractControl, FormControl, FormGroup, ReactiveFormsModule, ValidationErrors, Validators } from '@angular/forms';
import { LucideDynamicIcon } from '@lucide/angular';
import { startWith } from 'rxjs';

import {
  ApiError,
  Channel,
  Destination,
  Policy,
  PolicyAction,
  PolicyCreate,
  PolicyValidationResponse,
  ProfileInfo,
} from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';

export const ALLOWED_DESTINATIONS: Record<PolicyAction, Destination[]> = {
  ALLOW: ['CLOUD', 'LOCAL'],
  REDACT: ['CLOUD', 'LOCAL'],
  LOCAL_ONLY: ['LOCAL'],
  BLOCK: ['NONE'],
};

const ACTION_HELP: Record<PolicyAction, string> = {
  ALLOW: 'Permit processing after all mandatory checks. Values are left unredacted.',
  REDACT: 'Replace matching values with placeholders and validate the transformed payload.',
  LOCAL_ONLY: 'Redact matching values and prevent any cloud transmission.',
  BLOCK: 'Reject AI processing entirely. No local model or cloud call is made.',
};

const PROFILE_RE = /^[a-z0-9][a-z0-9-]{1,39}$/;

function profileListValidator(control: AbstractControl<string>): ValidationErrors | null {
  const items = splitList(control.value);
  const bad = items.filter((p) => !PROFILE_RE.test(p));
  return bad.length ? { profiles: bad.join(', ') } : null;
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean);
}

@Component({
  selector: 'app-policy-editor',
  imports: [ReactiveFormsModule, LucideDynamicIcon, ErrorAlert],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '(document:keydown.escape)': 'closed.emit()' },
  templateUrl: './policy-editor.html',
  styleUrl: './policy-editor.scss',
})
export class PolicyEditor implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly policy = input<Policy | null>(null);
  readonly categories = input.required<string[]>();
  readonly profiles = input.required<ProfileInfo[]>();
  readonly saved = output<Policy>();
  readonly closed = output<void>();

  protected readonly actions: PolicyAction[] = ['ALLOW', 'REDACT', 'LOCAL_ONLY', 'BLOCK'];
  protected readonly channels: Channel[] = ['voice', 'chat', 'email', 'sms'];
  protected readonly actionHelp = ACTION_HELP;

  protected readonly saving = signal(false);
  protected readonly validating = signal(false);
  protected readonly serverError = signal<ApiError | null>(null);
  protected readonly validation = signal<PolicyValidationResponse | null>(null);

  protected readonly form = new FormGroup({
    policy_id: new FormControl('', { nonNullable: true, validators: [Validators.pattern(/^([a-z0-9][a-z0-9-]{2,63})?$/)] }),
    name: new FormControl('', { nonNullable: true, validators: [Validators.required, Validators.minLength(3), Validators.maxLength(80)] }),
    description: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(500)] }),
    enabled: new FormControl(true, { nonNullable: true }),
    priority: new FormControl(500, { nonNullable: true, validators: [Validators.required, Validators.min(1), Validators.max(1000)] }),
    entity_categories: new FormControl<string[]>([], { nonNullable: true, validators: [Validators.required] }),
    action: new FormControl<PolicyAction>('REDACT', { nonNullable: true }),
    destination: new FormControl<Destination>('CLOUD', { nonNullable: true }),
    profiles: new FormControl('', { nonNullable: true, validators: [profileListValidator] }),
    channels: new FormControl<Channel[]>([], { nonNullable: true }),
    min_confidence: new FormControl(0, { nonNullable: true, validators: [Validators.required, Validators.min(0), Validators.max(1)] }),
  });

  private readonly actionValue = toSignal(
    this.form.controls.action.valueChanges.pipe(startWith(this.form.controls.action.value)),
    { initialValue: 'REDACT' as PolicyAction },
  );
  private readonly selectedCategories = toSignal(
    this.form.controls.entity_categories.valueChanges.pipe(startWith(this.form.controls.entity_categories.value)),
    { initialValue: [] as string[] },
  );
  protected readonly destinations = computed(() => ALLOWED_DESTINATIONS[this.actionValue()]);
  protected readonly isEdit = computed(() => this.policy() !== null);

  ngOnInit(): void {
    const p = this.policy();
    if (p) {
      this.form.setValue({
        policy_id: p.policy_id,
        name: p.name,
        description: p.description,
        enabled: p.enabled,
        priority: p.priority,
        entity_categories: [...p.entity_categories],
        action: p.action,
        destination: p.destination,
        profiles: p.conditions.profiles.join(', '),
        channels: [...p.conditions.channels],
        min_confidence: p.conditions.min_confidence,
      });
      this.form.controls.policy_id.disable();
    }
    this.form.controls.action.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((action) => {
      const allowed = ALLOWED_DESTINATIONS[action];
      if (!allowed.includes(this.form.controls.destination.value)) {
        this.form.controls.destination.setValue(allowed[0]);
      }
    });
    this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.validation.set(null));
  }

  protected hasCategory(category: string): boolean {
    return this.selectedCategories().includes(category);
  }

  protected toggleCategory(category: string, checked: boolean): void {
    const control = this.form.controls.entity_categories;
    let next = control.value.filter((c) => c !== category);
    if (checked) {
      // ANY cannot be combined with specific categories.
      next = category === 'ANY' ? ['ANY'] : [...next.filter((c) => c !== 'ANY'), category];
    }
    control.setValue(next);
    control.markAsTouched();
  }

  protected hasChannel(channel: Channel): boolean {
    return this.form.controls.channels.value.includes(channel);
  }

  protected toggleChannel(channel: Channel, checked: boolean): void {
    const control = this.form.controls.channels;
    const next = control.value.filter((c) => c !== channel);
    control.setValue(checked ? [...next, channel] : next);
  }

  protected addProfile(id: string): void {
    const current = splitList(this.form.controls.profiles.value);
    if (!current.includes(id)) {
      this.form.controls.profiles.setValue([...current, id].join(', '));
    }
  }

  private payload(): PolicyCreate {
    const v = this.form.getRawValue();
    return {
      policy_id: this.isEdit() ? undefined : v.policy_id || null,
      name: v.name.trim(),
      description: v.description.trim(),
      enabled: v.enabled,
      priority: Number(v.priority),
      entity_categories: v.entity_categories,
      action: v.action,
      destination: v.destination,
      conditions: { profiles: splitList(v.profiles), channels: v.channels, min_confidence: Number(v.min_confidence) },
    };
  }

  protected validate(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }
    const body = this.payload();
    if (this.isEdit()) {
      body.policy_id = this.policy()!.policy_id;
    }
    this.validating.set(true);
    this.serverError.set(null);
    this.api.validatePolicy(body).subscribe({
      next: (res) => {
        this.validation.set(res);
        this.validating.set(false);
      },
      error: (err: ApiError) => {
        this.serverError.set(err);
        this.validating.set(false);
      },
    });
  }

  protected save(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid || this.saving()) {
      return;
    }
    this.saving.set(true);
    this.serverError.set(null);
    const body = this.payload();
    const existing = this.policy();
    const request$ = existing
      ? this.api.updatePolicy(existing.policy_id, { ...body, policy_id: undefined } as PolicyCreate)
      : this.api.createPolicy(body);
    request$.subscribe({
      next: (policy) => {
        this.saving.set(false);
        this.saved.emit(policy);
      },
      error: (err: ApiError) => {
        this.saving.set(false);
        this.serverError.set(
          err.status === 401 ? { ...err, message: `${err.message} Enter the administrator key in Settings.` } : err,
        );
      },
    });
  }
}
