import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AiSystem,
  AiSystemCreate,
  AppConfig,
  AuditEvent,
  AuditFilters,
  AuditListResponse,
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
  MetricsSummary,
  Policy,
  PolicyCreate,
  PolicyDefinition,
  PolicyListResponse,
  PolicyValidationResponse,
  ProcessRequest,
  ProfileInfo,
  SampleTranscript,
  Severity,
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
