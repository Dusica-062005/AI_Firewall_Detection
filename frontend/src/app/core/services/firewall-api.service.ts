import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AiSystem,
  AiSystemCreate,
  AppConfig,
  AuditEvent,
  AuditFilters,
  AudioProcessResult,
  AuditListResponse,
  BenchmarkLatest,
  BreachReport,
  BreachReportSource,
  BreachReportVerify,
  CanaryCompare,
  CanaryRunDetail,
  CanaryRunSummary,
  CanarySetName,
  CanarySetSummary,
  Channel,
  ComplianceOverview,
  Controls,
  DataRequest,
  DialPosition,
  ReceiptListResponse,
  VerifyResult,
  DataRequestCreate,
  EvidencePack,
  FirewallResult,
  FrameworkId,
  HealthResponse,
  Incident,
  IncidentAdvance,
  IncidentCreate,
  IncidentStatus,
  IntegrationsStatus,
  MeasurementStatus,
  MetricsSummary,
  Policy,
  PolicyCreate,
  PolicyDefinition,
  PolicyListResponse,
  PolicyValidationResponse,
  ProcessingMode,
  ProcessRequest,
  ProfileInfo,
  QualityLatest,
  SampleTranscript,
  Severity,
  SizingRequest,
  SizingResponse,
  SystemStatus,
  SystemTaskStatus,
} from '../models/api.models';
import { RuntimeConfigService } from './runtime-config.service';

/** All HTTP calls to the firewall backend. Components never build URLs themselves. */
@Injectable({ providedIn: 'root' })
export class FirewallApiService {
  private readonly http = inject(HttpClient);
  private readonly config = inject(RuntimeConfigService);

  private url(path: string): string {
    return this.config.url(path);
  }

  // System
  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(this.url('/health'));
  }

  integrations(): Observable<IntegrationsStatus> {
    return this.http.get<IntegrationsStatus>(this.url('/integrations/status'));
  }

  appConfig(): Observable<AppConfig> {
    return this.http.get<AppConfig>(this.url('/config'));
  }

  metrics(windowHours = 24): Observable<MetricsSummary> {
    return this.http.get<MetricsSummary>(this.url('/metrics/summary'), {
      params: new HttpParams().set('window_hours', windowHours),
    });
  }

  samples(): Observable<SampleTranscript[]> {
    return this.http.get<SampleTranscript[]>(this.url('/samples'));
  }

  // Firewall
  inspect(body: Omit<ProcessRequest, 'mode'>): Observable<FirewallResult> {
    return this.http.post<FirewallResult>(this.url('/inspect'), body);
  }

  process(body: ProcessRequest): Observable<FirewallResult> {
    return this.http.post<FirewallResult>(this.url('/process'), body);
  }

  // Policies
  policies(): Observable<PolicyListResponse> {
    return this.http.get<PolicyListResponse>(this.url('/policies'));
  }

  profiles(): Observable<{ items: ProfileInfo[] }> {
    return this.http.get<{ items: ProfileInfo[] }>(this.url('/policies/profiles'));
  }

  entityCategories(): Observable<{ items: string[] }> {
    return this.http.get<{ items: string[] }>(this.url('/policies/entity-categories'));
  }

  createPolicy(body: PolicyCreate): Observable<Policy> {
    return this.http.post<Policy>(this.url('/policies'), body);
  }

  updatePolicy(policyId: string, body: PolicyDefinition): Observable<Policy> {
    return this.http.put<Policy>(this.url(`/policies/${encodeURIComponent(policyId)}`), body);
  }

  deletePolicy(policyId: string): Observable<void> {
    return this.http.delete<void>(this.url(`/policies/${encodeURIComponent(policyId)}`));
  }

  validatePolicy(body: PolicyCreate): Observable<PolicyValidationResponse> {
    return this.http.post<PolicyValidationResponse>(this.url('/policies/validate'), body);
  }

  resetPolicies(): Observable<PolicyListResponse> {
    return this.http.post<PolicyListResponse>(this.url('/policies/reset'), {});
  }

  // Audit
  audit(filters: AuditFilters, page: number, pageSize: number): Observable<AuditListResponse> {
    let params = new HttpParams().set('page', page).set('page_size', pageSize);
    for (const [key, value] of Object.entries(filters)) {
      if (value) {
        params = params.set(key, value);
      }
    }
    return this.http.get<AuditListResponse>(this.url('/audit'), { params });
  }

  auditEvent(eventId: string): Observable<AuditEvent> {
    return this.http.get<AuditEvent>(this.url(`/audit/${encodeURIComponent(eventId)}`));
  }

  purgeAudit(): Observable<{ deleted: number; retention_days: number }> {
    return this.http.post<{ deleted: number; retention_days: number }>(this.url('/audit/purge'), {});
  }

  // Trust layer: operator controls and signed receipts
  controls(): Observable<Controls> {
    return this.http.get<Controls>(this.url('/controls'));
  }

  setKillSwitch(enabled: boolean): Observable<Controls> {
    return this.http.put<Controls>(this.url('/controls/kill-switch'), { enabled });
  }

  setDial(position: DialPosition): Observable<Controls> {
    return this.http.put<Controls>(this.url('/controls/dial'), { position });
  }

  receipts(page: number, pageSize: number): Observable<ReceiptListResponse> {
    return this.http.get<ReceiptListResponse>(this.url('/receipts'), {
      params: new HttpParams().set('page', page).set('page_size', pageSize),
    });
  }

  verifyReceipts(tamperDemo: boolean): Observable<VerifyResult> {
    return this.http.post<VerifyResult>(this.url('/receipts/verify'), {}, {
      params: new HttpParams().set('tamper_demo', tamperDemo),
    });
  }

  // Measurements: leak canaries and dial quality
  canarySet(set: CanarySetName = 'main'): Observable<CanarySetSummary> {
    return this.http.get<CanarySetSummary>(this.url('/canaries/set'), { params: new HttpParams().set('set', set) });
  }

  canaryRuns(): Observable<CanaryRunSummary[]> {
    return this.http.get<CanaryRunSummary[]>(this.url('/canaries/runs'));
  }

  canaryRun(runId: string): Observable<CanaryRunDetail> {
    return this.http.get<CanaryRunDetail>(this.url(`/canaries/runs/${encodeURIComponent(runId)}`));
  }

  startCanaryRun(normalizeOn: boolean, set: CanarySetName = 'main'): Observable<{ run_id: string; status: MeasurementStatus }> {
    return this.http.post<{ run_id: string; status: MeasurementStatus }>(this.url('/canaries/runs'), {
      normalize_on: normalizeOn,
      set,
    });
  }

  compareCanaryRuns(a: string, b: string): Observable<CanaryCompare> {
    return this.http.get<CanaryCompare>(this.url('/canaries/compare'), { params: new HttpParams().set('a', a).set('b', b) });
  }

  qualityLatest(): Observable<QualityLatest> {
    return this.http.get<QualityLatest>(this.url('/quality/latest'));
  }

  startQualityRun(): Observable<{ run_id: string; status: MeasurementStatus }> {
    return this.http.post<{ run_id: string; status: MeasurementStatus }>(this.url('/quality/runs'), {});
  }

  // Audio: local transcription and bleeping. The file goes to the local backend only.
  processAudio(file: File, profile: string, channel: Channel, mode: ProcessingMode, bleep: boolean): Observable<AudioProcessResult> {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('profile', profile);
    form.append('channel', channel);
    form.append('mode', mode);
    return this.http.post<AudioProcessResult>(this.url('/process-audio'), form, {
      params: new HttpParams().set('bleep', bleep),
    });
  }

  // Latency benchmark and Hardware Fit Calculator
  benchmarkLatest(): Observable<BenchmarkLatest> {
    return this.http.get<BenchmarkLatest>(this.url('/benchmarks/latest'));
  }

  startBenchmark(body: { calls_per_level: number; include_transcription: boolean }): Observable<{ run_id: string; status: MeasurementStatus }> {
    return this.http.post<{ run_id: string; status: MeasurementStatus }>(this.url('/benchmarks/runs'), body);
  }

  sizingEstimate(body: SizingRequest): Observable<SizingResponse> {
    return this.http.post<SizingResponse>(this.url('/sizing/estimate'), body);
  }

  // Breach Report Generator: drafts only, nothing is sent or filed
  breachReports(): Observable<BreachReport[]> {
    return this.http.get<BreachReport[]>(this.url('/breach-reports'));
  }

  draftBreachReport(body: { source: BreachReportSource; ref?: string; from?: string; to?: string }): Observable<BreachReport> {
    return this.http.post<BreachReport>(this.url('/breach-reports'), body);
  }

  verifyBreachReport(reportId: string): Observable<BreachReportVerify> {
    return this.http.get<BreachReportVerify>(this.url(`/breach-reports/${reportId}/verify`));
  }

  reviewBreachReport(reportId: string, reviewer: string, decision: 'REVIEWED' | 'WITHDRAWN', note: string): Observable<BreachReport> {
    return this.http.post<BreachReport>(this.url(`/breach-reports/${reportId}/review`), { reviewer, decision, note });
  }

  breachReportIncident(reportId: string): Observable<BreachReport> {
    return this.http.post<BreachReport>(this.url(`/breach-reports/${reportId}/incident`), {});
  }

  breachReportMarkdown(reportId: string): Observable<string> {
    return this.http.get(this.url(`/breach-reports/${reportId}/markdown`), { responseType: 'text' });
  }

  // Compliance & incident center
  complianceOverview(): Observable<ComplianceOverview> {
    return this.http.get<ComplianceOverview>(this.url('/compliance/overview'));
  }

  evidencePack(framework: FrameworkId): Observable<EvidencePack> {
    return this.http.get<EvidencePack>(this.url(`/compliance/evidence/${framework}`));
  }

  evidenceMarkdown(framework: FrameworkId): Observable<string> {
    return this.http.get(this.url(`/compliance/evidence/${framework}/markdown`), { responseType: 'text' });
  }

  aiSystems(): Observable<{ items: AiSystem[]; total: number }> {
    return this.http.get<{ items: AiSystem[]; total: number }>(this.url('/compliance/systems'));
  }

  createAiSystem(body: AiSystemCreate): Observable<AiSystem> {
    return this.http.post<AiSystem>(this.url('/compliance/systems'), body);
  }

  reviewAiSystem(systemId: string, status: SystemStatus | null): Observable<AiSystem> {
    return this.http.post<AiSystem>(this.url(`/compliance/systems/${systemId}/review`), status ? { status } : {});
  }

  incidents(status: IncidentStatus | null, severity: Severity | null): Observable<{ items: Incident[]; total: number }> {
    let params = new HttpParams();
    if (status) {
      params = params.set('status', status);
    }
    if (severity) {
      params = params.set('severity', severity);
    }
    return this.http.get<{ items: Incident[]; total: number }>(this.url('/compliance/incidents'), { params });
  }

  createIncident(body: IncidentCreate): Observable<Incident> {
    return this.http.post<Incident>(this.url('/compliance/incidents'), body);
  }

  advanceIncident(incidentId: string, body: IncidentAdvance): Observable<Incident> {
    return this.http.post<Incident>(this.url(`/compliance/incidents/${incidentId}/advance`), body);
  }

  updateIncident(incidentId: string, body: { owner?: string; severity?: Severity }): Observable<Incident> {
    return this.http.put<Incident>(this.url(`/compliance/incidents/${incidentId}`), body);
  }

  dataRequests(): Observable<{ items: DataRequest[]; total: number }> {
    return this.http.get<{ items: DataRequest[]; total: number }>(this.url('/compliance/data-requests'));
  }

  createDataRequest(body: DataRequestCreate): Observable<DataRequest> {
    return this.http.post<DataRequest>(this.url('/compliance/data-requests'), body);
  }

  updateDataRequestSystem(requestId: string, systemId: string, status: SystemTaskStatus, note = ''): Observable<DataRequest> {
    return this.http.put<DataRequest>(this.url(`/compliance/data-requests/${requestId}/systems/${systemId}`), { status, note });
  }
}
