import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, SizingResponse } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';

/**
 * Hardware Fit Calculator (Feature 7): sizing from a measured benchmark run only. The formula is
 * shown with the real numbers, so a partner can check every step. Nothing is extrapolated.
 */
@Component({
  selector: 'app-sizing',
  imports: [ReactiveFormsModule, DecimalPipe, RouterLink, LucideDynamicIcon, StatusBadge, ErrorAlert],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sizing.html',
  styleUrl: './sizing.scss',
})
export class Sizing {
  private readonly api = inject(FirewallApiService);

  protected readonly form = new FormGroup({
    seats: new FormControl(300, { nonNullable: true, validators: [Validators.required, Validators.min(1)] }),
    calls_per_hour: new FormControl(1200, { nonNullable: true, validators: [Validators.required, Validators.min(1)] }),
    avg_call_minutes: new FormControl(5, { nonNullable: true, validators: [Validators.required, Validators.min(0.1)] }),
    peak_factor: new FormControl(1.5, { nonNullable: true, validators: [Validators.required, Validators.min(1)] }),
    mode: new FormControl<'post_call' | 'live'>('post_call', { nonNullable: true }),
  });

  protected readonly result = signal<SizingResponse | null>(null);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly loading = signal(false);

  protected estimate(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.api.sizingEstimate(this.form.getRawValue()).subscribe({
      next: (result) => {
        this.result.set(result);
        this.loading.set(false);
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.loading.set(false);
      },
    });
  }
}
