import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, inject, model, signal } from '@angular/core';
import { LucideDynamicIcon } from '@lucide/angular';

import { ApiError, EvidencePack, FrameworkId } from '../../core/models/api.models';
import { FirewallApiService } from '../../core/services/firewall-api.service';
import { NotificationService } from '../../core/services/notification.service';
import { ErrorAlert } from '../../shared/components/error-alert';
import { StatusBadge } from '../../shared/components/status-badge';
import { scoreTone } from './compliance-overview';

const FRAMEWORKS: { id: FrameworkId; label: string }[] = [
  { id: 'GDPR', label: 'GDPR' },
  { id: 'HIPAA', label: 'HIPAA' },
  { id: 'ISO_42001', label: 'ISO 42001' },
  { id: 'SOC_2', label: 'SOC 2' },
];

@Component({
  selector: 'app-evidence-pack',
  imports: [DatePipe, LucideDynamicIcon, StatusBadge, ErrorAlert],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './evidence-pack.html',
  styleUrl: './compliance.scss',
})
export class EvidencePackTab {
  private readonly api = inject(FirewallApiService);
  private readonly notify = inject(NotificationService);

  readonly framework = model.required<FrameworkId>();

  protected readonly frameworks = FRAMEWORKS;
  protected readonly pack = signal<EvidencePack | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal<ApiError | null>(null);
  protected readonly tone = scoreTone;

  constructor() {
    effect(() => this.load(this.framework()));
  }

  protected load(framework: FrameworkId = this.framework()): void {
    this.loading.set(true);
    this.error.set(null);
    this.api.evidencePack(framework).subscribe({
      next: (res) => {
        // Ignore a slow response for a framework the user has already moved away from.
        if (res.framework === this.framework()) {
          this.pack.set(res);
          this.loading.set(false);
        }
      },
      error: (err: ApiError) => {
        this.error.set(err);
        this.pack.set(null);
        this.loading.set(false);
      },
    });
  }

  protected setFramework(id: FrameworkId): void {
    this.framework.set(id);
  }

  protected downloadMarkdown(): void {
    const framework = this.framework();
    this.api.evidenceMarkdown(framework).subscribe({
      next: (text) => this.save(text, `evidence-${framework.toLowerCase()}.md`, 'text/markdown'),
      error: () => this.notify.error('The Markdown report could not be generated.'),
    });
  }

  protected downloadJson(): void {
    const pack = this.pack();
    if (pack) {
      this.save(JSON.stringify(pack, null, 2), `evidence-${pack.framework.toLowerCase()}.json`, 'application/json');
    }
  }

  protected print(): void {
    window.print();
  }

  private save(content: string, filename: string, type: string): void {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }
}
