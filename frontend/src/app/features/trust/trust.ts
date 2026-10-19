import { DatePipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, input, signal } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, DialPosition, Receipt, ReceiptListResponse, VerifyResult } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { SystemStatusService } from '../../core/services/system-status.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { HumanizePipe } from '../../shared/pipes/format.pipes';

const PAGE_SIZE = 25;

/** Trust layer: kill switch (Feature 3), privacy-utility dial (Feature 4) and signed receipts (Feature 2). */
@Component({
  selector: 'app-trust',
  imports: [DatePipe, JsonPipe, LucideDynamicIcon, StatusBadge, ErrorAlert, HumanizePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './trust.html',
  styleUrl: './trust.scss',
  host: { '(document:keydown.escape)': 'closeReceipt()' },
})
export class Trust implements OnInit {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);
  protected readonly status = inject(SystemStatusService);

  /** Bound from the ?receipt= query parameter (links from the Inspector). */
  readonly receipt = input<string | undefined>();

  protected readonly controls = this.status.controls;
  protected readonly controlsError = signal<ApiError | null>(null);
  protected readonly saving = signal(false);

  protected readonly receipts = signal<ReceiptListResponse | null>(null);
  protected readonly receiptsError = signal<ApiError | null>(null);
  protected readonly loading = signal(false);
  protected readonly page = signal(1);
  protected readonly pageCount = computed(() => Math.max(1, Math.ceil((this.receipts()?.total ?? 0) / PAGE_SIZE)));
  protected readonly selected = signal<Receipt | null>(null);

  protected readonly verifying = signal<'chain' | 'tamper' | null>(null);
  protected readonly verifyResult = signal<VerifyResult | null>(null);
  protected readonly verifyError = signal<ApiError | null>(null);

  ngOnInit(): void {
    this.status.refresh();
    this.loadReceipts();
  }

  protected loadReceipts(): void {
    this.loading.set(true);
    this.receiptsError.set(null);
    this.api.receipts(this.page(), PAGE_SIZE).subscribe({
      next: (res) => {
        this.receipts.set(res);
        this.loading.set(false);
        const wanted = this.receipt();
        if (wanted && !this.selected()) {
          this.selected.set(res.items.find((r) => r.receipt_id === wanted) ?? null);
        }
      },
      error: (err: ApiError) => {
        this.receiptsError.set(err);
        this.loading.set(false);
      },
    });
  }

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.pageCount()));
    this.loadReceipts();
  }

  protected toggleKillSwitch(): void {
    const next = !(this.controls()?.kill_switch ?? false);
    this.saving.set(true);
    this.controlsError.set(null);
    this.api.setKillSwitch(next).subscribe({
      next: (controls) => {
        this.status.controls.set(controls);
        this.saving.set(false);
        this.notify.success(next ? 'Kill switch on: the cloud path is blocked.' : 'Kill switch off: the cloud path is restored.');
      },
      error: (err: ApiError) => {
        this.controlsError.set(err);
        this.saving.set(false);
      },
    });
  }

  protected setDial(position: DialPosition): void {
    if (position === this.controls()?.dial) {
      return;
    }
    this.saving.set(true);
    this.controlsError.set(null);
    this.api.setDial(position).subscribe({
      next: (controls) => {
        this.status.controls.set(controls);
        this.saving.set(false);
      },
      error: (err: ApiError) => {
        this.controlsError.set(err);
        this.saving.set(false);
      },
    });
  }

  protected verify(tamperDemo: boolean): void {
    this.verifying.set(tamperDemo ? 'tamper' : 'chain');
    this.verifyError.set(null);
    this.verifyResult.set(null);
    this.api.verifyReceipts(tamperDemo).subscribe({
      next: (result) => {
        this.verifyResult.set(result);
        this.verifying.set(null);
      },
      error: (err: ApiError) => {
        this.verifyError.set(err);
        this.verifying.set(null);
      },
    });
  }

  protected open(receipt: Receipt): void {
    this.selected.set(receipt);
  }

  protected closeReceipt(): void {
    this.selected.set(null);
  }

  protected entitySummary(counts: Record<string, number>): string {
    const parts = Object.entries(counts).map(([k, v]) => `${k} x${v}`);
    return parts.length ? parts.join(', ') : 'None';
  }
}
