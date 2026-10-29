import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { testProviders } from '../../testing/test-providers';
import { FirewallResult } from '../core/models/api.models';
import { LiveCallService } from '../core/services/live-call.service';
import { Inspector } from './inspector/inspector';
import { BreachReports } from './compliance/breach-reports';
import { InspectorDetails } from './inspector/inspector-details';
import { InspectorStateService } from './inspector/inspector-state.service';
import { BenchmarkTab } from './measurements/benchmark';
import { Measurements } from './measurements/measurements';
import { Overview } from './overview/overview';
import { Settings } from './settings/settings';
import { Sizing } from './sizing/sizing';

const TRANSCRIPT = 'My name is John Smith, my patient ID is 48291, and I need help with my appointment.';

function blockedResult(): FirewallResult {
  return {
    request_id: 'req-12345678', event_id: null, operation: 'PROCESS', mode: 'full', profile: 'restricted', channel: 'voice',
    decision: 'BLOCKED', status: 'COMPLETED', authorized_destination: 'NONE', policy_version: 'ps-1',
    decisive_policy_id: 'restricted-block-phi', error_category: null, reasons: ['Blocked by policy.'], warnings: [],
    transcript_chars: TRANSCRIPT.length, entities: [], entity_counts: {}, matched_policies: [],
    redacted_transcript: 'My name is [PERSON_1], my patient ID is [PATIENT_ID_1], and I need help with my appointment.',
    tokens: [], routing: null, agent_view: null, receipt: null,
    summary: { status: 'NOT_AUTHORIZED', text: null, model: null, latency_ms: null, message: 'Not run.' },
    outbound: {
      status: 'NOT_AUTHORIZED', reached_receiver: false, simulated: true, target: null, payload: null,
      receiver_response: null, http_status: null, latency_ms: null, validation: [], message: 'No outbound request.',
    },
    steps: [], latency: {
      detection_ms: 10, policy_ms: 1, protection_ms: 1, local_ai_ms: null, validation_ms: null, cloud_ms: null,
      audit_ms: 3, total_ms: 14,
    },
    created_at: '2026-09-29T10:00:00Z',
  };
}

function text(el: HTMLElement): string {
  return (el.textContent ?? '').replace(/\s+/g, ' ');
}

describe('Inspector', () => {
  let controller: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: testProviders() });
    controller = TestBed.inject(HttpTestingController);
    TestBed.inject(InspectorStateService).result.set(null);
  });

  async function setup() {
    const fixture = TestBed.createComponent(Inspector);
    fixture.detectChanges();
    controller.expectOne('/api/samples').flush([]);
    controller.expectOne('/api/policies/profiles').flush({
      items: [{ id: 'restricted', name: 'Restricted lockdown', description: '', applicable_policies: 6 }],
    });
    controller.expectOne('/api/config').flush({}, { status: 500, statusText: 'err' });
    await fixture.whenStable();
    return fixture;
  }

  it('shows an actionable error when the backend is unreachable', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance as unknown as { form: Inspector['form']; submit(): void };
    component.form.patchValue({ transcript: TRANSCRIPT, profile: 'restricted' });
    component.submit();
    controller.expectOne('/api/process').error(new ProgressEvent('error'), { status: 0 });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(text(el)).toContain('The request was not processed');
    expect(text(el)).toContain('not reachable');
  });

  it('shows validation details returned by the backend', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance as unknown as { form: Inspector['form']; submit(): void };
    component.form.patchValue({ transcript: TRANSCRIPT, profile: 'restricted' });
    component.submit();
    controller.expectOne('/api/process').flush(
      { error: { code: 'UNKNOWN_PROFILE', message: "Unknown policy profile 'x'.", request_id: 'abc12345', details: [] } },
      { status: 422, statusText: 'Unprocessable' },
    );
    await fixture.whenStable();
    expect(text(fixture.nativeElement)).toContain("Unknown policy profile 'x'.");
    expect(text(fixture.nativeElement)).toContain('Request ID abc12345');
  });

  it('does not submit an empty transcript', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance as unknown as { submit(): void };
    component.submit();
    controller.expectNone('/api/process');
    await fixture.whenStable();
    expect(text(fixture.nativeElement)).toContain('Enter a transcript to analyze.');
  });

  it('renders a blocked decision without claiming a cloud handoff', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance as unknown as { form: Inspector['form']; submit(): void };
    component.form.patchValue({ transcript: TRANSCRIPT, profile: 'restricted' });
    component.submit();
    controller.expectOne('/api/process').flush(blockedResult());
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(text(el)).toContain('BLOCKED');
    expect(text(el)).toContain('AI processing not permitted');
    expect(text(el)).toContain('Nothing left the firewall.');
    expect(el.querySelector('a[href="/inspector/result"]')?.textContent).toContain('View full details');
  });

  it('shows the full result on the details page', async () => {
    const state = TestBed.inject(InspectorStateService);
    state.result.set(blockedResult());
    state.submittedTranscript.set(TRANSCRIPT);
    const fixture = TestBed.createComponent(InspectorDetails);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(text(el)).toContain('BLOCKED');
    expect(text(el)).toContain('Before and after');
    expect(el.querySelector('.placeholder-token')?.textContent).toBe('[PERSON_1]');
  });

  it('points back to the Inspector when there is no result', async () => {
    const fixture = TestBed.createComponent(InspectorDetails);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(text(fixture.nativeElement)).toContain('No result to show');
  });

  it('shows live captions and then the whole-call result', async () => {
    const live = TestBed.inject(LiveCallService);
    const fixture = await setup();
    const component = fixture.componentInstance as unknown as { inputKind: Inspector['inputKind'] };
    component.inputKind.set('live');
    live.state.set('live');
    live.seconds.set(6);
    live.captions.set([
      { index: 0, text: 'My name is [PERSON_1].', withheld: false },
      { index: 1, text: '[caption withheld: protection unavailable]', withheld: true },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(text(el)).toContain('Live · 6 s');
    expect(el.querySelectorAll('.caption').length).toBe(2);
    expect(el.querySelector('.caption--withheld')).not.toBeNull();
    expect(text(el)).not.toContain('Transcribe and process');

    // After End call: each stage with its time, and the protected transcript before the models finish.
    const t0 = Date.now();
    live.state.set('processing');
    live.steps.set([
      { stage: 'transcribing', startedAt: t0 - 4000 },
      { stage: 'protecting', startedAt: t0 - 2000 },
      { stage: 'protected', startedAt: t0 - 2000 },
      { stage: 'local_ai', startedAt: t0 - 2000 },
    ]);
    live.preview.set({ decision: 'REDACTED', redactedTranscript: 'My name is [PERSON_1].' });
    live.now.set(t0 + 5000);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(text(el)).toContain('Transcribing the whole call (local)2 s');
    expect(text(el)).toContain('Local AI summary (on this machine)7 s');
    expect(el.querySelectorAll('.live-steps li.is-done').length).toBe(2);
    expect(text(el)).toContain('Protected transcript (final) · REDACTED');
    expect(text(el)).toContain('My name is [PERSON_1].');

    live.result.set({
      ...blockedResult(),
      transcription: {
        model: 'base', language: 'en', duration_s: 6, transcription_ms: 900, format: 'wav', transcript: TRANSCRIPT, words: [],
      },
      bleep: null,
    });
    live.state.set('done');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(text(el)).toContain('Call processed');
    expect(text(el)).toContain('Local transcription');
    expect(text(el)).toContain('BLOCKED');
    live.result.set(null);
    live.steps.set([]);
    live.preview.set(null);
    live.state.set('idle');
  });
});

describe('Overview', () => {
  it('distinguishes unavailable metrics from zero values', async () => {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Overview);
    fixture.detectChanges();
    // Audit succeeds first; metrics then fail, which fails the combined dashboard load.
    controller.expectOne((r) => r.url === '/api/audit').flush({ items: [], total: 0, page: 1, page_size: 8 });
    controller.expectOne((r) => r.url === '/api/metrics/summary').error(new ProgressEvent('error'), { status: 0 });
    controller.expectOne('/api/integrations/status').error(new ProgressEvent('error'), { status: 0 });
    controller.match('/api/health').forEach((r) => r.error(new ProgressEvent('error'), { status: 0 }));
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(text(el)).toContain('Metrics are unavailable');
    expect(text(el)).toContain('Chart unavailable');
    const values = Array.from(el.querySelectorAll('.kpi__value')).map((v) => v.textContent?.trim());
    expect(values.every((v) => v === '-')).toBe(true);
  });
});

describe('Measurements', () => {
  const RUN_ID = 'canary-20261022T063000Z-a1b2c3';
  const SET = {
    version: 'canaries-v1', calls: 200, planted_values: 390,
    by_language: { en: 100, hi: 25 }, by_script: {}, by_difficulty: { plain: 105 }, by_type: {},
  };
  const bucket = (key: string, recall: number, leakRate: number) => ({
    key, n_calls: 200, n_planted: 390, detected: Math.round(recall * 390), recall,
    leaked: Math.round(leakRate * 390), leak_rate: leakRate,
  });

  function summary(status: 'RUNNING' | 'COMPLETED', done = 200) {
    const completed = status === 'COMPLETED';
    return {
      run_id: RUN_ID, status, created_at: '2026-10-22T06:30:00Z', finished_at: completed ? '2026-10-22T06:30:06Z' : null,
      canary_set_version: 'canaries-v1', rule_version: 'rules-0123456789ab', normalize_on: true, dial: 'max_quality',
      kill_switch_on: false, machine: 'Windows-11 (8 CPUs)', duration_s: completed ? 5.3 : null, progress_done: done,
      progress_total: 200, error: null, n_planted: completed ? 390 : null, recall: completed ? 0.8923 : null,
      leak_rate: completed ? 0.1179 : null,
    };
  }

  async function setup(runs: unknown[]) {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Measurements);
    fixture.detectChanges();
    const setRequest = controller.expectOne((r) => r.url === '/api/canaries/set');
    expect(setRequest.request.params.get('set')).toBe('main');
    setRequest.flush(SET);
    controller.expectOne('/api/canaries/runs').flush(runs);
    await fixture.whenStable();
    return { fixture, controller };
  }

  it('shows "Not measured yet" when there is no run', async () => {
    const { fixture } = await setup([]);
    const el = text(fixture.nativeElement);
    expect(el).toContain('Not measured yet');
    expect(el).not.toContain('%');
    fixture.destroy();
  });

  it('renders recall and leak rate from a stored run, with n and run ID', async () => {
    const { fixture, controller } = await setup([summary('COMPLETED')]);
    controller.expectOne(`/api/canaries/runs/${RUN_ID}`).flush({
      ...summary('COMPLETED'), low_confidence_threshold: 0.6,
      metrics: {
        overall: bucket('all', 0.8923, 0.1179), by_type: [], by_difficulty: [bucket('spelled_digits', 0.8148, 0.1728)],
        by_language: [], by_script: [bucket('hi/native', 0.4737, 0.6316)], route_counts: { CLOUD: 160 },
        route_reasons: {}, payloads_sent: 160, received_lines: 160, low_confidence_holds: 0, call_errors: 0,
      },
      misses: [], leaks: [],
    });
    await fixture.whenStable();
    const el = text(fixture.nativeElement);
    expect(el).toContain('89.2%');
    expect(el).toContain('11.8%');
    expect(el).toContain('n=390');
    expect(el).toContain(RUN_ID);
    expect(el).toContain('rules-0123456789ab');
    expect(el).toContain('Spelled digits');
    expect(el).not.toContain('Not measured yet');
    fixture.destroy();
  });

  it('disables Run while a run is in progress and shows progress', async () => {
    const { fixture } = await setup([summary('RUNNING', 10)]);
    const el = fixture.nativeElement as HTMLElement;
    const button = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Run canary batch'));
    expect(button?.disabled).toBe(true);
    expect(text(el)).toContain('Running: 10 / 200 calls');
    expect(el.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('10');
    fixture.destroy();
  });
});

describe('Hardware Fit', () => {
  async function estimate(response: object) {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Sizing);
    fixture.detectChanges();
    (fixture.componentInstance as unknown as { estimate(): void }).estimate();
    const request = controller.expectOne('/api/sizing/estimate');
    expect(request.request.body).toEqual({ seats: 300, calls_per_hour: 1200, avg_call_minutes: 5, peak_factor: 1.5, mode: 'post_call' });
    request.flush(response);
    await fixture.whenStable();
    return text(fixture.nativeElement);
  }

  const base = {
    inputs: { seats: 300, calls_per_hour: 1200, avg_call_minutes: 5, peak_factor: 1.5, mode: 'post_call' },
    budget_s: 60, required_rate_per_min: 30, caveats: ['A Mitel Edge appliance was not benchmarked.'],
  };

  it('says "Not measured yet" when there is no benchmark', async () => {
    const el = await estimate({
      ...base, status: 'NOT_MEASURED', message: 'Not measured yet. Run a benchmark.', benchmark_run_id: null,
      formula: null, recommendation: null, caveats: [],
    });
    expect(el).toContain('Not measured yet');
    expect(el).toContain('Go to the Benchmark tab');
    expect(el).not.toContain('Machines');
  });

  it('renders the formula with the measured numbers and the run ID', async () => {
    const el = await estimate({
      ...base, status: 'OK', message: '4 machine(s) like the benchmarked one.', benchmark_run_id: 'bench-20261022T080000Z-abc123',
      formula: {
        required_rate: '1200 calls/hour x 1.5 peak factor / 60 = 30.00 calls/min',
        per_machine_rate: '8.28 calls/min measured at concurrency 2 (warm p95 18.82 s <= 60 s budget, n=8)',
        machines: 'ceil(30.00 / 8.28) = 4',
        headroom: '(4 x 8.28 - 30.00) / (4 x 8.28) = 9.4%',
      },
      recommendation: {
        machines: 4, concurrency_per_machine: 2, per_machine_rate_per_min: 8.28, headroom_pct: 9.4,
        expected_latency: { p50_s: 13.22, p95_s: 18.82, n: 8 }, model: 'llama3.2:3b',
        machine: { cpu: 'Test CPU', physical_cores: 4, ram_gb: 15.4 }, gpu: 'not detected',
      },
    });
    expect(el).toContain('ceil(30.00 / 8.28) = 4');
    expect(el).toContain('bench-20261022T080000Z-abc123');
    expect(el).toContain('13.22 s / 18.82 s');
    expect(el).toContain('Mitel Edge appliance was not benchmarked');
  });
});

describe('Breach reports', () => {
  it('shows the DRAFT watermark on a report', async () => {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(BreachReports);
    fixture.detectChanges();
    const watermark = 'DRAFT for compliance review. Not filed. Not legal advice.';
    controller.expectOne('/api/breach-reports').flush([{
      report_id: 'brr-0123456789ab', status: 'DRAFT', created_at: '2026-10-22T08:00:00Z', updated_at: '2026-10-22T08:00:00Z',
      source_type: 'canary_run', source_ref: 'canary-20261022T063000Z-a1b2c3', query: {}, incident_id: null,
      reviewer: null, reviewed_at: null, review_note: null,
      content: {
        watermark, title: 'Draft breach report: canary run', what_happened: 'One synthetic call leaked.',
        affected_requests: 1, categories: { PATIENT_ID: 1 }, reasons: {}, routes: { CLOUD: 1 }, kill_switch: { off: 1 },
        dials: { max_quality: 1 }, receipt_ids: ['rcp-0123456789abcdef'], window: { first: null, last: null },
        chain: { ok: true, count: 9, reason: 'Chain intact.' }, incident: null, regulators: [], regulator_note: 'Directional only.',
        synthetic_appendix: [], privacy: '',
      },
    }]);
    controller.match('/api/canaries/runs').forEach((r) => r.flush([]));
    controller.match('/api/compliance/incidents').forEach((r) => r.flush({ items: [], total: 0 }));
    await fixture.whenStable();
    fixture.nativeElement.querySelector('tbody tr').click();
    await fixture.whenStable();
    expect(text(fixture.nativeElement)).toContain(watermark);
    expect(fixture.nativeElement.querySelectorAll('.watermark').length).toBe(2);
  });
});

describe('Benchmark', () => {
  it('disables Run while a benchmark is running', async () => {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(BenchmarkTab);
    fixture.detectChanges();
    controller.expectOne('/api/benchmarks/latest').flush({
      run: { run_id: 'bench-20261022T080000Z-abc123', status: 'RUNNING', created_at: '2026-10-22T08:00:00Z', finished_at: null,
        config: {}, machine: {}, models: {}, cold: null, levels: [], budget_s: 5, verdict: null, verdict_reason: null,
        duration_s: null, progress_done: 3, progress_total: 41, error: null },
      completed: null,
    });
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    const button = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('Run benchmark'));
    expect(button?.disabled).toBe(true);
    expect(text(el)).toContain('Running: 3 / 41 calls');
    expect(text(el)).toContain('Not measured yet');
    fixture.destroy();
  });
});

describe('Settings', () => {
  it('warns honestly when the local model is missing', async () => {
    TestBed.configureTestingModule({ providers: testProviders() });
    const controller = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(Settings);
    fixture.detectChanges();
    controller.expectOne('/api/config').flush({
      environment: 'test', version: '0.1.0', cors_origins: ['http://localhost:4200'], max_transcript_chars: 10000,
      max_request_bytes: 65536,
      detection: { engine: 'Microsoft Presidio', spacy_model: 'en_core_web_md', status: 'READY', message: '', load_seconds: 1,
        score_threshold: 0.35, low_confidence_threshold: 0.6, expose_detected_values: true, unmatched_entity_action: 'LOCAL_ONLY',
        normalize_numbers: true },
      recognizers: [],
      policy: { status: 'READY', message: '', policy_count: 7, policy_version: 'ps-1', seed_file: 'default.yaml', precedence: '' },
      ollama: { base_url: 'http://localhost:11434', model: 'llama3.2:3b', timeout_seconds: 45, cloud_fallback: false },
      cloudlink: { base_url: 'http://localhost:8100', timeout_seconds: 5, simulated: true,
        api_key: { configured: true, display: 'configured (hidden)' }, retries: 0 },
      audit: { retention_days: 30, event_count: 0, oldest_event_at: null, stores_raw_transcripts: false, stores_entity_values: false },
      admin_auth_enabled: false,
    });
    controller.match('/api/health').forEach((r) => r.error(new ProgressEvent('error'), { status: 0 }));
    controller.expectOne('/api/integrations/status').flush({
      checked_at: '2026-09-29T10:00:00Z',
      ollama: { status: 'MODEL_MISSING', base_url: 'http://localhost:11434', model: 'llama3.2:3b', model_available: false,
        available_models: [], latency_ms: 3, message: "Model 'llama3.2:3b' is not installed. Run: ollama pull llama3.2:3b" },
      cloudlink: { status: 'CONNECTED', base_url: 'http://localhost:8100', simulated: true, receipts_count: 0, latency_ms: 2, message: 'ok' },
    });
    await fixture.whenStable();
    const el = text(fixture.nativeElement);
    expect(el).toContain('ollama pull llama3.2:3b');
    expect(el).toContain('AI summaries are unavailable');
    expect(el).toContain('configured (hidden)');
    expect(el).toContain('Mock integration');
    expect(el).toContain('Backend health unavailable');
  });
});
