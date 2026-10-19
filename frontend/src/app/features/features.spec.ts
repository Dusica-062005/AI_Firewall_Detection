import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { testProviders } from '../../testing/test-providers';
import { FirewallResult } from '../core/models/api.models';
import { Inspector } from './inspector/inspector';
import { InspectorStateService } from './inspector/inspector-state.service';
import { Overview } from './overview/overview';
import { Settings } from './settings/settings';

const TRANSCRIPT = 'My name is John Smith, my patient ID is 48291, and I need help with my appointment.';

function blockedResult(): FirewallResult {
  return {
    request_id: 'req-12345678', event_id: null, operation: 'PROCESS', mode: 'full', profile: 'restricted', channel: 'voice',
    decision: 'BLOCKED', status: 'COMPLETED', authorized_destination: 'NONE', policy_version: 'ps-1',
    decisive_policy_id: 'restricted-block-phi', error_category: null, reasons: ['Blocked by policy.'], warnings: [],
    transcript_chars: TRANSCRIPT.length, entities: [], entity_counts: {}, matched_policies: [],
    redacted_transcript: 'My name is [PERSON], my patient ID is [PATIENT_ID], and I need help with my appointment.',
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
    expect(text(el)).toContain('No model or cloud call was made');
    expect(el.querySelector('.placeholder-token')?.textContent).toBe('[PERSON]');
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
        score_threshold: 0.35, low_confidence_threshold: 0.6, expose_detected_values: true, unmatched_entity_action: 'LOCAL_ONLY' },
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
    expect(el).toContain('There is no cloud-model fallback');
    expect(el).toContain('configured (hidden)');
    expect(el).toContain('Mock integration');
    expect(el).toContain('Backend health unavailable');
  });
});
