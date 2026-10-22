// Typed mirrors of the backend Pydantic schemas (see docs/api-contract.md).

export type FinalDecision = 'ALLOWED' | 'REDACTED' | 'BLOCKED' | 'LOCAL_ONLY' | 'PROCESSING_FAILED';
export type ProcessingStatus = 'COMPLETED' | 'COMPLETED_WITH_WARNINGS' | 'FAILED';
export type StepStatus = 'COMPLETED' | 'SKIPPED' | 'BLOCKED' | 'FAILED' | 'WARNING';
export type Destination = 'NONE' | 'LOCAL' | 'CLOUD';
export type PolicyAction = 'ALLOW' | 'REDACT' | 'LOCAL_ONLY' | 'BLOCK';
export type Channel = 'voice' | 'chat' | 'email' | 'sms';
export type ProcessingMode = 'inspect' | 'local' | 'full';

export interface ApiErrorBody {
  code: string;
  message: string;
  request_id: string | null;
  details: { loc?: string[]; msg: string; type?: string }[];
}

/** Normalised error produced by the error interceptor. */
export interface ApiError {
  status: number;
  code: string;
  message: string;
  requestId: string | null;
  details: string[];
}

export interface ComponentHealth {
  status: string;
  message: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  time: string;
  components: Record<string, ComponentHealth>;
}

export interface OllamaStatus {
  status: 'CONNECTED' | 'MODEL_MISSING' | 'UNREACHABLE';
  base_url: string;
  model: string;
  model_available: boolean;
  available_models: string[];
  latency_ms: number | null;
  message: string;
}

export interface CloudLinkStatus {
  status: 'CONNECTED' | 'UNREACHABLE' | 'ERROR';
  base_url: string;
  simulated: boolean;
  receipts_count: number | null;
  cloud_model: string | null;
  latency_ms: number | null;
  message: string;
}

export interface IntegrationsStatus {
  checked_at: string;
  ollama: OllamaStatus;
  cloudlink: CloudLinkStatus;
}

export interface EntityResult {
  entity_type: string;
  start: number;
  end: number;
  score: number;
  low_confidence: boolean;
  recognizer: string;
  value: string | null;
  action: string;
  destination: Destination;
  policy_id: string;
  policy_name: string;
  reason: string;
}

export interface MatchedPolicyResult {
  policy_id: string;
  name: string;
  action: PolicyAction;
  destination: Destination;
  priority: number;
  matched_categories: string[];
}

export interface ProcessingStep {
  key: 'received' | 'analyzed' | 'policy' | 'protected' | 'ai' | 'audited';
  label: string;
  status: StepStatus;
  duration_ms: number | null;
  detail: string;
}

export interface SummaryInfo {
  status: string;
  text: string | null;
  model: string | null;
  latency_ms: number | null;
  message: string;
}

export interface ValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface OutboundInfo {
  status: string;
  reached_receiver: boolean;
  simulated: boolean;
  target: string | null;
  payload: Record<string, unknown> | null;
  receiver_response: Record<string, unknown> | null;
  http_status: number | null;
  latency_ms: number | null;
  validation: ValidationCheck[];
  message: string;
}

export type Route = 'LOCAL' | 'CLOUD' | 'NONE';
export type DialPosition = 'max_privacy' | 'balanced' | 'max_quality';

export interface TokenResult {
  token: string;
  entity_type: string;
  value: string | null;
}

export interface RoutingInfo {
  route: Route;
  reason: string;
  message: string;
  kill_switch: boolean;
  dial: DialPosition;
  cloud_model: string | null;
  cloud_summary_status: string | null;
  cloud_summary: string | null;
  cloud_latency_ms: number | null;
}

export interface AgentView {
  status: 'REHYDRATED' | 'TOKENS_ONLY' | 'NO_SUMMARY';
  source: 'CLOUD' | 'LOCAL' | 'NONE';
  summary: string | null;
  tokenized_summary: string | null;
  message: string;
}

export interface ReceiptRef {
  receipt_id: string;
  seq: number;
  hash: string;
  signed: boolean;
}

export interface LatencyBreakdown {
  /** Audio calls only; not part of total_ms. */
  transcription_ms?: number | null;
  detection_ms: number | null;
  policy_ms: number | null;
  protection_ms: number | null;
  local_ai_ms: number | null;
  validation_ms: number | null;
  cloud_ms: number | null;
  audit_ms: number | null;
  total_ms: number;
}

export interface FirewallResult {
  request_id: string;
  event_id: string | null;
  operation: 'INSPECT' | 'PROCESS';
  mode: ProcessingMode;
  profile: string;
  channel: Channel;
  decision: FinalDecision;
  status: ProcessingStatus;
  authorized_destination: Destination;
  policy_version: string | null;
  decisive_policy_id: string | null;
  error_category: string | null;
  reasons: string[];
  warnings: string[];
  transcript_chars: number;
  entities: EntityResult[];
  entity_counts: Record<string, number>;
  matched_policies: MatchedPolicyResult[];
  redacted_transcript: string | null;
  tokens: TokenResult[];
  summary: SummaryInfo;
  outbound: OutboundInfo;
  routing: RoutingInfo | null;
  agent_view: AgentView | null;
  receipt: ReceiptRef | null;
  steps: ProcessingStep[];
  latency: LatencyBreakdown;
  created_at: string;
}

export interface ProcessRequest {
  transcript: string;
  profile: string;
  channel: Channel;
  mode: ProcessingMode;
}

export interface SampleTranscript {
  id: string;
  title: string;
  description: string;
  profile: string;
  channel: Channel;
  transcript: string;
}

export interface PolicyConditions {
  profiles: string[];
  channels: Channel[];
  min_confidence: number;
}

export interface PolicyDefinition {
  name: string;
  description: string;
  enabled: boolean;
  priority: number;
  entity_categories: string[];
  action: PolicyAction;
  destination: Destination;
  conditions: PolicyConditions;
}

export interface Policy extends PolicyDefinition {
  policy_id: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PolicyCreate extends PolicyDefinition {
  policy_id?: string | null;
}

export interface PolicyListResponse {
  items: Policy[];
  policy_version: string;
  total: number;
}

export interface PolicyValidationResponse {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ProfileInfo {
  id: string;
  name: string;
  description: string;
  applicable_policies: number;
}

export interface AuditEvent {
  event_id: string;
  request_id: string;
  created_at: string;
  operation: string;
  mode: string;
  profile: string;
  channel: string;
  decision: FinalDecision;
  status: ProcessingStatus;
  destination: Destination;
  local_ai_status: string;
  cloud_status: string;
  policy_version: string;
  decisive_policy_id: string;
  policy_ids: string[];
  entity_counts: Record<string, number>;
  latency_ms: Record<string, number | null>;
  total_latency_ms: number;
  error_category: string | null;
  transcript_chars: number;
  warnings: string[];
  cloud_receipt_id: string | null;
}

export interface AuditListResponse {
  items: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditFilters {
  date_from?: string | null;
  date_to?: string | null;
  decision?: string | null;
  policy_id?: string | null;
  status?: string | null;
  destination?: string | null;
  request_id?: string | null;
}

export interface LatencyStats {
  count: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

export interface TimeBucket {
  start: string;
  allowed: number;
  redacted: number;
  local_only: number;
  blocked: number;
  failed: number;
}

export interface MetricsSummary {
  generated_at: string;
  window_hours: number;
  total_requests: number;
  decision_counts: Record<FinalDecision, number>;
  status_counts: Record<string, number>;
  destination_counts: Record<Destination, number>;
  entity_category_counts: Record<string, number>;
  total_entities: number;
  cloud_handoffs_sent: number;
  local_summaries_generated: number;
  latency: Record<'total' | 'detection' | 'policy' | 'local_ai' | 'cloud', LatencyStats>;
  timeline: TimeBucket[];
}

export interface RecognizerInfo {
  category: string;
  description: string;
  limitations: string;
  sources: string[];
}

export interface AppConfig {
  environment: string;
  version: string;
  cors_origins: string[];
  max_transcript_chars: number;
  max_request_bytes: number;
  detection: {
    engine: string;
    spacy_model: string;
    status: string;
    message: string;
    load_seconds: number | null;
    score_threshold: number;
    low_confidence_threshold: number;
    expose_detected_values: boolean;
    unmatched_entity_action: string;
    normalize_numbers: boolean;
  };
  recognizers: RecognizerInfo[];
  policy: {
    status: string;
    message: string;
    policy_count: number;
    policy_version: string | null;
    seed_file: string;
    precedence: string;
  };
  ollama: { base_url: string; model: string; timeout_seconds: number; cloud_fallback: boolean };
  cloudlink: {
    base_url: string;
    timeout_seconds: number;
    simulated: boolean;
    api_key: { configured: boolean; display: string };
    retries: number;
  };
  transcription?: {
    engine: string;
    model: string;
    device: string;
    compute_type: string;
    status: string;
    message: string;
    max_audio_seconds: number;
    max_audio_bytes: number;
    stores_audio: boolean;
  };
  audit: {
    retention_days: number;
    event_count: number;
    oldest_event_at: string | null;
    stores_raw_transcripts: boolean;
    stores_entity_values: boolean;
  };
  admin_auth_enabled: boolean;
  trust?: {
    vault: { status: string; message: string };
    receipt_signing: { status: string; message: string; key_id: string | null };
    low_confidence_stays_local: boolean;
    cloud_stand_in_model: string | null;
  };
}

// ---- Trust layer: controls and signed receipts ----

export interface DialPositionInfo {
  id: DialPosition;
  label: string;
  description: string;
}

export interface Controls {
  kill_switch: boolean;
  cloud_path: 'ACTIVE' | 'BLOCKED';
  dial: DialPosition;
  kill_switch_updated_at: string | null;
  dial_updated_at: string | null;
  dial_positions: DialPositionInfo[];
}

export interface ReceiptBody {
  schema: string;
  receipt_id: string;
  seq: number;
  timestamp: string;
  prev_hash: string;
  request_id: string;
  event_id: string | null;
  operation: string;
  decision: FinalDecision;
  policy_version: string;
  entity_counts: Record<string, number>;
  tokens_created: number;
  route: Route;
  route_reason: string;
  local_model: string | null;
  cloud_model: string | null;
  cloud_sent: boolean;
  protected_values_left: boolean;
  allowed_categories_sent: string[];
  kill_switch: boolean;
  dial: DialPosition;
  normalize_on: boolean;
  /** Audio calls only: format, duration, model and transcription time. Never audio or text. */
  audio?: { format: string; duration_s: number; model: string; transcription_ms: number } | null;
}

export interface Receipt {
  seq: number;
  receipt_id: string;
  request_id: string;
  created_at: string;
  hash: string;
  prev_hash: string;
  signed: boolean;
  key_id: string | null;
  body: ReceiptBody;
}

export interface ReceiptListResponse {
  items: Receipt[];
  total: number;
  page: number;
  page_size: number;
  signing: { status: string; message: string; key_id: string | null };
}

export interface VerifyResult {
  ok: boolean;
  verifier: 'offline-script' | 'in-process';
  tamper_demo: boolean;
  exit_code: number | null;
  output: string;
  in_process_ok: boolean;
  in_process_reason: string;
  count: number;
}

// ---- Measurements: leak canaries (Feature 5) and dial quality (Feature 4) ----

export type MeasurementStatus = 'RUNNING' | 'COMPLETED' | 'FAILED';
/** main: the 200-call set; holdout: new templates that check detection changes for overfitting. */
export type CanarySetName = 'main' | 'holdout';

export interface CanarySetSummary {
  version: string;
  calls: number;
  planted_values: number;
  by_language: Record<string, number>;
  by_script: Record<string, number>;
  by_difficulty: Record<string, number>;
  by_type: Record<string, number>;
}

/** Recall and leak rate for one slice of the canary set. Rates are null when n is 0. */
export interface CanaryBucket {
  key: string;
  n_calls: number;
  n_planted: number;
  detected: number;
  recall: number | null;
  leaked: number;
  leak_rate: number | null;
}

export interface CanaryMetrics {
  overall: CanaryBucket;
  by_type: CanaryBucket[];
  by_difficulty: CanaryBucket[];
  by_language: CanaryBucket[];
  by_script: CanaryBucket[];
  route_counts: Record<string, number>;
  route_reasons: Record<string, number>;
  payloads_sent: number;
  received_lines: number;
  low_confidence_holds: number;
  call_errors: number;
}

export interface CanaryMiss {
  call_id: string;
  type: string;
  difficulty: string;
  language: string;
  script: string;
  surface: string;
}

export interface CanaryLeak extends CanaryMiss {
  field: string;
}

export interface CanaryRunSummary {
  run_id: string;
  status: MeasurementStatus;
  created_at: string;
  finished_at: string | null;
  canary_set_version: string;
  rule_version: string;
  normalize_on: boolean;
  dial: string;
  kill_switch_on: boolean;
  machine: string;
  duration_s: number | null;
  progress_done: number;
  progress_total: number;
  error: string | null;
  n_planted: number | null;
  recall: number | null;
  leak_rate: number | null;
}

export interface CanaryRunDetail extends CanaryRunSummary {
  low_confidence_threshold: number;
  metrics: CanaryMetrics | null;
  misses: CanaryMiss[];
  leaks: CanaryLeak[];
}

export interface CanaryCompareRow {
  group: 'overall' | 'type' | 'difficulty' | 'language' | 'script';
  key: string;
  a: CanaryBucket | null;
  b: CanaryBucket | null;
  recall_delta: number | null;
  leak_rate_delta: number | null;
}

export interface CanaryCompare {
  a: CanaryRunSummary;
  b: CanaryRunSummary;
  rows: CanaryCompareRow[];
}

export interface QualityPositionScore {
  position: DialPosition;
  score: number | null;
  n: number;
  n_null: number;
}

export interface QualitySampleScore {
  sample_id: string;
  title: string;
  position: DialPosition;
  similarity: number | null;
  decision: string;
  route: string;
  source: string;
  summary_status: string;
}

export interface QualityRun {
  run_id: string;
  status: MeasurementStatus;
  created_at: string;
  finished_at: string | null;
  sample_ids: string[];
  reference_model: string;
  local_model: string;
  cloud_model: string | null;
  embed_model: string;
  kill_switch_on: boolean;
  machine: string;
  duration_s: number | null;
  progress_done: number;
  progress_total: number;
  error: string | null;
  positions: QualityPositionScore[];
  samples: QualitySampleScore[];
  note: string;
}

export interface QualityLatest {
  run: QualityRun | null;
  completed: QualityRun | null;
}

// ---- Audio: local transcription (FR-1) and bleeping (FR-16) ----

export interface WordInfo {
  word: string;
  start_s: number;
  end_s: number;
  char_start: number;
  char_end: number;
}

export interface TranscriptionInfo {
  model: string;
  language: string;
  duration_s: number;
  transcription_ms: number;
  format: string;
  /** The local transcript; null when EXPOSE_DETECTED_VALUES is off. */
  transcript: string | null;
  words: WordInfo[];
}

export interface BleepInfo {
  style: string;
  ranges: { start_s: number; end_s: number }[];
  content_type: string;
  audio_base64: string;
}

export interface AudioProcessResult extends FirewallResult {
  transcription: TranscriptionInfo;
  bleep: BleepInfo | null;
}

// ---- Latency benchmark (NFR-2) and Hardware Fit Calculator (Feature 7) ----

export type BenchmarkVerdict = 'REAL_TIME_CAPABLE' | 'POST_CALL_WRAP_UP' | 'NOT_DETERMINED';

export interface StageStats {
  n: number;
  mean_ms: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
}

export interface BenchmarkLevel {
  concurrency: number;
  n_calls: number;
  wall_s: number;
  calls_per_minute: number | null;
  stages: Record<string, StageStats | null>;
  failures: Record<string, number>;
}

export interface BenchmarkRun {
  run_id: string;
  status: MeasurementStatus;
  created_at: string;
  finished_at: string | null;
  config: { calls_per_level: number; concurrency: number[]; include_transcription: boolean; dial: string; inputs: string[] };
  machine: { platform?: string; cpu?: string; physical_cores?: number | null; logical_cores?: number | null; ram_gb?: number | null };
  models: { local?: string; cloud_stand_in?: string | null; whisper?: string; ollama_version?: string | null; gpu?: string };
  cold: { stages: Record<string, number>; failures: string[] } | null;
  levels: BenchmarkLevel[];
  budget_s: number;
  verdict: BenchmarkVerdict | null;
  verdict_reason: string | null;
  duration_s: number | null;
  progress_done: number;
  progress_total: number;
  error: string | null;
}

export interface BenchmarkLatest {
  run: BenchmarkRun | null;
  completed: BenchmarkRun | null;
}

export interface SizingRequest {
  seats: number;
  calls_per_hour: number;
  avg_call_minutes: number;
  peak_factor: number;
  mode: 'post_call' | 'live';
}

export interface SizingResponse {
  status: 'OK' | 'NOT_MEASURED' | 'NO_FIT';
  message: string;
  inputs: SizingRequest & { seats: number };
  budget_s: number;
  required_rate_per_min: number;
  benchmark_run_id: string | null;
  formula: { required_rate: string; per_machine_rate: string; machines: string; headroom: string } | null;
  recommendation: {
    machines: number;
    concurrency_per_machine: number;
    per_machine_rate_per_min: number;
    headroom_pct: number;
    expected_latency: { p50_s: number; p95_s: number; n: number };
    model: string | null;
    machine: { cpu?: string; physical_cores?: number | null; logical_cores?: number | null; ram_gb?: number | null; platform?: string };
    gpu: string;
  } | null;
  caveats: string[];
}

// ---- Breach Report Generator (Feature 8) ----

export type BreachReportStatus = 'DRAFT' | 'REVIEWED' | 'WITHDRAWN';
export type BreachReportSource = 'canary_run' | 'incident' | 'window';

export interface BreachReportContent {
  watermark: string;
  title: string;
  what_happened: string;
  affected_requests: number;
  categories: Record<string, number>;
  reasons: Record<string, number>;
  routes: Record<string, number>;
  kill_switch: Record<string, number>;
  dials: Record<string, number>;
  receipt_ids: string[];
  window: { first: string | null; last: string | null };
  chain: { ok: boolean; count: number; reason: string };
  incident: { incident_id: string; status: string; severity: string; contained_at: string | null; sla_state: string } | null;
  regulators: { framework: string; note: string }[];
  regulator_note: string;
  synthetic_appendix: { call_id: string; type: string; field: string; surface: string }[];
  privacy: string;
}

export interface BreachReport {
  report_id: string;
  status: BreachReportStatus;
  created_at: string;
  updated_at: string;
  source_type: BreachReportSource;
  source_ref: string | null;
  query: Record<string, string | null>;
  content: BreachReportContent;
  incident_id: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface BreachReportVerify {
  ok: boolean;
  mismatches: { field: string; report: unknown; records: unknown }[];
  chain: { ok: boolean; count: number; reason: string } | null;
}

// ---- Compliance & incident center ----

export type FrameworkId = 'GDPR' | 'HIPAA' | 'ISO_42001' | 'SOC_2';
export type ControlStatus = 'PASS' | 'PARTIAL' | 'FAIL';
export type Hosting = 'LOCAL' | 'CLOUD';
export type SystemStatus = 'APPROVED' | 'UNDER_REVIEW' | 'RETIRED';
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type IncidentType = 'WRONG_ANSWER' | 'DATA_EXPOSURE' | 'BIASED_OUTPUT' | 'POLICY_BYPASS' | 'OTHER';
export type IncidentStatus = 'REPORTED' | 'CONTAINED' | 'ROOT_CAUSE_IDENTIFIED' | 'CLOSED';
export type SlaState = 'ON_TRACK' | 'AT_RISK' | 'BREACHED' | 'MET' | 'MISSED';
export type DataRequestType = 'ERASURE' | 'ACCESS';
export type DataRequestStatus = 'OPEN' | 'COMPLETED';
export type SystemTaskStatus = 'PENDING' | 'DONE' | 'NOT_HELD';

export interface ControlResult {
  control_id: string;
  title: string;
  description: string;
  reference: string;
  status: ControlStatus;
  evidence: string;
  remediation: string | null;
}

export interface FrameworkScore {
  framework: FrameworkId;
  name: string;
  score: number;
  pass_count: number;
  partial_count: number;
  fail_count: number;
  total: number;
  controls: ControlResult[];
}

export interface ComplianceKpis {
  ai_systems: number;
  reviews_overdue: number;
  open_incidents: number;
  sla_breached: number;
  open_data_requests: number;
  overdue_data_requests: number;
}

export interface ComplianceOverview {
  generated_at: string;
  overall_score: number;
  frameworks: FrameworkScore[];
  kpis: ComplianceKpis;
}

export interface AiSystem {
  system_id: string;
  name: string;
  owner: string;
  purpose: string;
  hosting: Hosting;
  data_categories: string[];
  status: SystemStatus;
  review_interval_days: number;
  last_reviewed_at: string;
  next_review_due: string;
  review_overdue: boolean;
  created_at: string;
}

export interface AiSystemCreate {
  name: string;
  owner: string;
  purpose: string;
  hosting: Hosting;
  data_categories: string[];
  status: SystemStatus;
  review_interval_days: number;
}

export interface IncidentTimelineEntry {
  at: string;
  action: string;
  note: string;
}

export interface Incident {
  incident_id: string;
  title: string;
  description: string;
  incident_type: IncidentType;
  severity: Severity;
  status: IncidentStatus;
  owner: string | null;
  ai_system_id: string | null;
  related_event_id: string | null;
  created_at: string;
  updated_at: string;
  sla_due_at: string;
  sla_state: SlaState;
  sla_seconds_remaining: number | null;
  contained_at: string | null;
  closed_at: string | null;
  root_cause: string | null;
  resolution: string | null;
  timeline: IncidentTimelineEntry[];
}

export interface IncidentCreate {
  title: string;
  description: string;
  incident_type: IncidentType;
  severity: Severity;
  owner: string | null;
  ai_system_id: string | null;
  related_event_id: string | null;
}

export interface IncidentAdvance {
  note: string;
  root_cause?: string | null;
  resolution?: string | null;
}

export interface DataRequestSystem {
  system_id: string;
  system_name: string;
  status: SystemTaskStatus;
  note: string;
  updated_at: string | null;
}

export interface DataRequest {
  request_id: string;
  request_type: DataRequestType;
  subject_reference: string;
  status: DataRequestStatus;
  received_at: string;
  due_at: string;
  completed_at: string | null;
  days_remaining: number | null;
  overdue: boolean;
  systems_done: number;
  systems_total: number;
  systems: DataRequestSystem[];
}

export interface DataRequestCreate {
  request_type: DataRequestType;
  subject_reference: string;
  system_ids: string[];
}

export interface EvidencePack {
  framework: FrameworkId;
  framework_name: string;
  generated_at: string;
  disclaimer: string;
  score: number;
  controls: ControlResult[];
  ai_systems: AiSystem[];
  policies: {
    policy_version: string;
    total: number;
    enabled: number;
    rules: { policy_id: string; name: string; enabled: boolean; action: string; destination: string; categories: string[]; profiles: string[] }[];
  };
  audit: {
    retention_days: number;
    event_count: number;
    oldest_event_at: string | null;
    stores_raw_transcripts: boolean;
    stores_entity_values: boolean;
    decision_counts: Record<string, number>;
  };
  incidents: {
    total: number;
    open: number;
    closed: number;
    contained_within_sla: number;
    sla_missed: number;
    sla_breached_open: number;
    by_severity: Record<string, number>;
  };
  data_requests: {
    total: number;
    open: number;
    completed: number;
    completed_on_time: number;
    completed_late: number;
    overdue_open: number;
  };
}
