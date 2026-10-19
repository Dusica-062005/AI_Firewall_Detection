import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import { BarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { EChartsType, init, use } from 'echarts/core';
import { SVGRenderer } from 'echarts/renderers';

import { TimeBucket } from '../../core/models/api.models';

use([BarChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer]);

// Decision colours validated for colour-vision separation (see docs/architecture.md).
const SERIES: { key: keyof Omit<TimeBucket, 'start'>; name: string; color: string }[] = [
  { key: 'allowed', name: 'Allowed', color: '#16805D' },
  { key: 'redacted', name: 'Redacted', color: '#245A9B' },
  { key: 'local_only', name: 'Local only', color: '#5B8FD0' },
  { key: 'blocked', name: 'Blocked', color: '#B42318' },
  { key: 'failed', name: 'Processing failed', color: '#B7791F' },
];

/** Stacked hourly decision counts. Only rendered from real metrics responses. */
@Component({
  selector: 'app-decision-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div #host class="chart" role="img" [attr.aria-label]="ariaLabel()"></div>`,
  styles: `
    .chart {
      width: 100%;
      height: 260px;
    }
  `,
})
export class DecisionChart {
  readonly buckets = input.required<TimeBucket[]>();

  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  private chart: EChartsType | null = null;

  constructor() {
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      this.chart = init(this.host().nativeElement, undefined, { renderer: 'svg' });
      const observer = new ResizeObserver(() => this.chart?.resize());
      observer.observe(this.host().nativeElement);
      this.render();
      destroyRef.onDestroy(() => {
        observer.disconnect();
        this.chart?.dispose();
      });
    });
    effect(() => {
      this.buckets();
      this.render();
    });
  }

  protected ariaLabel(): string {
    const totals = SERIES.map((s) => `${s.name} ${this.buckets().reduce((n, b) => n + b[s.key], 0)}`);
    return `Hourly processing decisions: ${totals.join(', ')}.`;
  }

  private render(): void {
    if (!this.chart) {
      return;
    }
    const buckets = this.buckets();
    const labels = buckets.map((b) =>
      new Date(b.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    );
    const lastIndex = SERIES.length - 1;
    this.chart.setOption(
      {
        animation: false,
        textStyle: { fontFamily: 'Segoe UI, system-ui, sans-serif', color: '#64748B' },
        grid: { left: 36, right: 12, top: 36, bottom: 28 },
        legend: {
          top: 0,
          left: 0,
          itemWidth: 10,
          itemHeight: 10,
          icon: 'roundRect',
          textStyle: { color: '#1F2937', fontSize: 12 },
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(36, 90, 155, 0.06)' } },
          borderColor: '#D8E0EA',
          textStyle: { color: '#1F2937', fontSize: 12 },
        },
        xAxis: {
          type: 'category',
          data: labels,
          axisLine: { lineStyle: { color: '#D8E0EA' } },
          axisTick: { show: false },
          axisLabel: { color: '#64748B', fontSize: 11, interval: 'auto', hideOverlap: true },
        },
        yAxis: {
          type: 'value',
          minInterval: 1,
          splitLine: { lineStyle: { color: '#EEF2F6' } },
          axisLabel: { color: '#64748B', fontSize: 11 },
        },
        series: SERIES.map((s, i) => ({
          name: s.name,
          type: 'bar',
          stack: 'decisions',
          barMaxWidth: 18,
          data: buckets.map((b) => b[s.key]),
          itemStyle: {
            color: s.color,
            borderColor: '#FFFFFF',
            borderWidth: 1,
            borderRadius: i === lastIndex ? [4, 4, 0, 0] : 0,
          },
          emphasis: { focus: 'series' },
        })),
      },
      { notMerge: true },
    );
  }
}
