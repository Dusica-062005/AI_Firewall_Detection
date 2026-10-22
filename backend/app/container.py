"""Builds the service graph. Tests pass transports and a pre-loaded analyzer."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import Engine

from app.ai.ollama_client import OllamaClient
from app.ai.summarizer import Summarizer
from app.audit.service import AuditService
from app.canaries.runner import CanaryRunner, rule_version
from app.compliance.data_requests import DataRequestService
from app.compliance.incidents import IncidentService
from app.compliance.service import ComplianceService
from app.compliance.systems import AiSystemService
from app.config import Settings
from app.db.compliance_repositories import AiSystemRepository, DataRequestRepository, IncidentRepository
from app.db.repositories import AuditRepository, PolicyRepository
from app.db.session import create_database
from app.detection.analyzer import SensitiveDataAnalyzer
from app.detection.recognizers import load_detection_config
from app.integrations.cloudlink_client import CloudLinkClient
from app.policy.engine import PolicyEngine
from app.policy.models import Action
from app.security.outbound_validator import OutboundValidator
from app.security.redactor import Redactor
from app.services.firewall_service import FirewallService
from app.services.policy_service import PolicyService
from app.services.processing_service import ProcessingService
from app.trust.controls import ControlsService
from app.trust.keys import load_fernet, load_signing_key
from app.trust.receipts import ReceiptService
from app.trust.vault import TokenVault


@dataclass
class Container:
    settings: Settings
    engine: Engine
    analyzer: SensitiveDataAnalyzer
    policy_service: PolicyService
    policy_repository: PolicyRepository
    audit_service: AuditService
    ai_systems: AiSystemService
    incidents: IncidentService
    data_requests: DataRequestService
    compliance: ComplianceService
    ollama: OllamaClient
    cloudlink: CloudLinkClient
    firewall: FirewallService
    processing: ProcessingService
    policy_status: dict
    controls: ControlsService
    vault: TokenVault
    receipts: ReceiptService
    canaries: CanaryRunner


def build_analyzer(settings: Settings) -> SensitiveDataAnalyzer:
    config = load_detection_config(settings.detection_config_file)
    return SensitiveDataAnalyzer(
        config=config,
        spacy_model=settings.spacy_model,
        score_threshold=settings.detection_score_threshold,
        low_confidence_threshold=settings.detection_low_confidence_threshold,
    )


def build_container(
    settings: Settings,
    analyzer: SensitiveDataAnalyzer | None = None,
    ollama_transport: httpx.AsyncBaseTransport | None = None,
    cloudlink_transport: httpx.AsyncBaseTransport | None = None,
) -> Container:
    engine, sessions = create_database(settings.database_url)
    policy_repo = PolicyRepository(sessions)
    audit_repo = AuditRepository(sessions)

    if analyzer is None:
        analyzer = build_analyzer(settings)
    analyzer.load()

    policy_service = PolicyService(policy_repo, settings.policy_seed_file, analyzer.categories)
    try:
        policy_service.initialize()
        policy_status = {"status": "READY", "message": "Policy configuration loaded."}
    except Exception as exc:  # noqa: BLE001 - requests fail closed while this is broken
        policy_status = {"status": "ERROR", "message": f"Policy configuration failed to load ({type(exc).__name__})."}

    audit_service = AuditService(audit_repo, settings.audit_retention_days)
    audit_service.purge_expired()

    ai_systems = AiSystemService(AiSystemRepository(sessions), analyzer.categories)
    ai_systems.initialize()
    incidents = IncidentService(IncidentRepository(sessions))
    data_requests = DataRequestService(DataRequestRepository(sessions), ai_systems)
    compliance = ComplianceService(settings, policy_service, audit_service, ai_systems, incidents, data_requests)

    ollama = OllamaClient(settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds, ollama_transport)
    cloudlink = CloudLinkClient(
        settings.cloudlink_base_url,
        settings.cloudlink_api_key.get_secret_value(),
        settings.cloudlink_timeout_seconds,
        cloudlink_transport,
    )

    controls = ControlsService(sessions, settings.default_dial)
    fernet, vault_status = load_fernet(settings.vault_key.get_secret_value())
    vault = TokenVault(sessions, fernet, vault_status)
    vault.purge_older_than(settings.audit_retention_days)
    signing_key, signing_status = load_signing_key(settings.receipt_signing_key.get_secret_value())
    receipts = ReceiptService(sessions, signing_key, signing_status)
    _publish_public_key(settings, receipts)

    firewall = FirewallService(
        analyzer=analyzer,
        engine=PolicyEngine(unmatched_entity_action=Action(settings.unmatched_entity_action)),
        redactor=Redactor(),
        validator=OutboundValidator(analyzer),
        policy_source=policy_repo.list,
    )
    processing = ProcessingService(
        firewall=firewall,
        summarizer=Summarizer(ollama),
        cloudlink=cloudlink,
        audit=audit_service,
        expose_detected_values=settings.expose_detected_values,
        controls=controls,
        vault=vault,
        receipts=receipts,
        low_confidence_stays_local=settings.route_low_confidence_local,
        normalize_on=settings.normalize_numbers,
    )
    canaries = CanaryRunner(
        sessions=sessions,
        processing=processing,
        controls=controls,
        received_log_file=settings.received_log_file,
        low_confidence_threshold=settings.detection_low_confidence_threshold,
        default_normalize=settings.normalize_numbers,
        rule_version_source=lambda: rule_version(settings.detection_config_file, policy_service.version()),
    )
    return Container(
        settings=settings,
        engine=engine,
        analyzer=analyzer,
        policy_service=policy_service,
        policy_repository=policy_repo,
        audit_service=audit_service,
        ai_systems=ai_systems,
        incidents=incidents,
        data_requests=data_requests,
        compliance=compliance,
        ollama=ollama,
        cloudlink=cloudlink,
        firewall=firewall,
        processing=processing,
        policy_status=policy_status,
        controls=controls,
        vault=vault,
        receipts=receipts,
        canaries=canaries,
    )


def _publish_public_key(settings: Settings, receipts: ReceiptService) -> None:
    """Write the receipt public key next to the data so the offline verifier can use it."""
    pem = receipts.public_key_pem
    if not pem:
        return
    try:
        settings.keys_dir.mkdir(parents=True, exist_ok=True)
        (settings.keys_dir / "receipt_public_key.pem").write_text(pem, encoding="ascii")
    except OSError:
        pass  # the key is also served by GET /api/receipts/public-key
