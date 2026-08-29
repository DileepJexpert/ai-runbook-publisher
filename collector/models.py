"""Data models for deterministic Spring Boot service fact collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceEvidence:
    file: str
    line_start: int | None = None
    line_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"file": self.file}
        if self.line_start is not None:
            result["lineStart"] = self.line_start
        if self.line_end is not None:
            result["lineEnd"] = self.line_end
        return result


@dataclass(frozen=True)
class ServiceMeta:
    name: str
    repository_name: str
    branch: str | None
    commit_sha: str
    origin_url: str | None
    working_tree_clean: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "repositoryName": self.repository_name,
            "branch": self.branch,
            "commitSha": self.commit_sha,
            "originUrl": self.origin_url,
            "workingTreeClean": self.working_tree_clean,
        }


@dataclass(frozen=True)
class BuildFacts:
    build_system: str  # MAVEN, GRADLE, UNKNOWN
    group_id: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    java_version: str | None = None
    spring_boot_version: str | None = None
    detected_dependencies: list[str] = field(default_factory=list)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "buildSystem": self.build_system,
            "groupId": self.group_id,
            "artifactId": self.artifact_id,
            "version": self.version,
            "javaVersion": self.java_version,
            "springBootVersion": self.spring_boot_version,
            "detectedDependencies": sorted(self.detected_dependencies),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class ConfigEntry:
    property_key: str
    status: str  # KNOWN_FROM_REPOSITORY, CHECK_CONFIG_PORTAL, PROTECTED_REPOSITORY_VALUE, PROTECTED_CHECK_CONFIG_PORTAL
    repository_value: Any | None = None
    config_key: str | None = None
    repository_default: Any | None = None
    sensitive: bool = False
    source_file: str | None = None
    profile: str | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "propertyKey": self.property_key,
            "status": self.status,
            "repositoryValue": self.repository_value,
            "configKey": self.config_key,
            "repositoryDefault": self.repository_default,
            "sensitive": self.sensitive,
            "sourceFile": self.source_file,
            "profile": self.profile,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class ApiEndpoint:
    http_method: str
    path: str
    controller_class: str
    handler_method: str
    request_body_type: str | None = None
    response_type: str | None = None
    path_variables: list[str] = field(default_factory=list)
    request_params: list[str] = field(default_factory=list)
    auth_annotations: list[str] = field(default_factory=list)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "httpMethod": self.http_method,
            "path": self.path,
            "controllerClass": self.controller_class,
            "handlerMethod": self.handler_method,
            "requestBodyType": self.request_body_type,
            "responseType": self.response_type,
            "pathVariables": sorted(self.path_variables),
            "requestParams": sorted(self.request_params),
            "authAnnotations": sorted(self.auth_annotations),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class ValidationRule:
    dto_class: str
    field_name: str
    annotation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    mechanical_description: str | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dtoClass": self.dto_class,
            "fieldName": self.field_name,
            "annotation": self.annotation,
            "parameters": self.parameters,
            "message": self.message,
            "mechanicalDescription": self.mechanical_description,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class KafkaConsumerFact:
    listener_class: str
    listener_method: str
    topic_expression: str | None = None
    topic_literal: str | None = None
    topic_config_key: str | None = None
    topic_default: str | None = None
    group_expression: str | None = None
    group_literal: str | None = None
    group_config_key: str | None = None
    group_default: str | None = None
    concurrency: str | None = None
    container_factory: str | None = None
    status: str = "KNOWN_FROM_REPOSITORY"  # KNOWN_FROM_REPOSITORY, CHECK_CONFIG_PORTAL
    retry_structure: dict[str, Any] | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "listenerClass": self.listener_class,
            "listenerMethod": self.listener_method,
            "topicExpression": self.topic_expression,
            "topicLiteral": self.topic_literal,
            "topicConfigKey": self.topic_config_key,
            "topicDefault": self.topic_default,
            "groupExpression": self.group_expression,
            "groupLiteral": self.group_literal,
            "groupConfigKey": self.group_config_key,
            "groupDefault": self.group_default,
            "concurrency": self.concurrency,
            "containerFactory": self.container_factory,
            "status": self.status,
            "retryStructure": self.retry_structure,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class KafkaProducerFact:
    caller_class: str
    caller_method: str
    topic_literal: str | None = None
    topic_config_key: str | None = None
    topic_default: str | None = None
    resolution: str = "RESOLVED_LITERAL"  # RESOLVED_LITERAL, RESOLVED_CONFIG, UNRESOLVED_REPOSITORY_EXPRESSION
    symbolic_reference: str | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "callerClass": self.caller_class,
            "callerMethod": self.caller_method,
            "topicLiteral": self.topic_literal,
            "topicConfigKey": self.topic_config_key,
            "topicDefault": self.topic_default,
            "resolution": self.resolution,
            "symbolicReference": self.symbolic_reference,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class KafkaFacts:
    consumers: list[KafkaConsumerFact] = field(default_factory=list)
    producers: list[KafkaProducerFact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "consumers": [c.to_dict() for c in sorted(self.consumers, key=lambda x: (x.listener_class, x.listener_method))],
            "producers": [p.to_dict() for p in sorted(self.producers, key=lambda x: (x.caller_class, x.caller_method))],
        }


@dataclass(frozen=True)
class DatabaseTableFact:
    table_name: str
    schema_name: str | None = None
    entity_class: str | None = None
    source_type: str = "JPA"  # JPA, FLYWAY, LIQUIBASE
    identifier_columns: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    observed_access: list[str] = field(default_factory=list)  # e.g. ["SAVE", "FIND_BY_ID"]
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tableName": self.table_name,
            "schemaName": self.schema_name,
            "entityClass": self.entity_class,
            "sourceType": self.source_type,
            "identifierColumns": sorted(self.identifier_columns),
            "columns": sorted(self.columns),
            "observedAccess": sorted(self.observed_access),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class RepositoryInterfaceFact:
    interface_name: str
    entity_class: str | None = None
    repository_type: str = "JpaRepository"
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interfaceName": self.interface_name,
            "entityClass": self.entity_class,
            "repositoryType": self.repository_type,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class AerospikeFact:
    detected: bool
    client_usage: list[str] = field(default_factory=list)
    namespace_property_key: str | None = None
    namespace_config_key: str | None = None
    namespace_default: str | None = None
    set_name: str | None = None
    set_config_key: str | None = None
    ttl_seconds: int | str | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "clientUsage": sorted(self.client_usage),
            "namespacePropertyKey": self.namespace_property_key,
            "namespaceConfigKey": self.namespace_config_key,
            "namespaceDefault": self.namespace_default,
            "setName": self.set_name,
            "setConfigKey": self.set_config_key,
            "ttlSeconds": self.ttl_seconds,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class DatastoreFacts:
    database_tables: list[DatabaseTableFact] = field(default_factory=list)
    repositories: list[RepositoryInterfaceFact] = field(default_factory=list)
    aerospike: list[AerospikeFact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "databaseTables": [t.to_dict() for t in sorted(self.database_tables, key=lambda x: (x.table_name, x.source_type))],
            "repositories": [r.to_dict() for r in sorted(self.repositories, key=lambda x: x.interface_name)],
            "aerospike": [a.to_dict() for a in self.aerospike],
        }


@dataclass(frozen=True)
class ResilienceFact:
    type: str  # CIRCUIT_BREAKER, RETRY, RATE_LIMITER, BULKHEAD, TIME_LIMITER
    name: str
    target_component: str | None = None
    max_attempts: int | None = None
    wait_duration: str | None = None
    timeout_duration: str | None = None
    property_key: str | None = None
    config_key: str | None = None
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "targetComponent": self.target_component,
            "maxAttempts": self.max_attempts,
            "waitDuration": self.wait_duration,
            "timeoutDuration": self.timeout_duration,
            "propertyKey": self.property_key,
            "configKey": self.config_key,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class DownstreamDependencyFact:
    client_type: str  # FEIGN, REST_CLIENT, REST_TEMPLATE, WEB_CLIENT
    client_name: str | None = None
    base_url: str | None = None
    url_config_key: str | None = None
    url_default: str | None = None
    timeout_config_key: str | None = None
    connect_timeout: str | None = None
    read_timeout: str | None = None
    resilience: list[ResilienceFact] = field(default_factory=list)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clientType": self.client_type,
            "clientName": self.client_name,
            "baseUrl": self.base_url,
            "urlConfigKey": self.url_config_key,
            "urlDefault": self.url_default,
            "timeoutConfigKey": self.timeout_config_key,
            "connectTimeout": self.connect_timeout,
            "readTimeout": self.read_timeout,
            "resilience": [r.to_dict() for r in sorted(self.resilience, key=lambda x: (x.type, x.name))],
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class CustomMetricFact:
    name: str
    metric_type: str  # COUNTER, TIMER, GAUGE, SUMMARY
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metricType": self.metric_type,
            "description": self.description,
            "tags": sorted(self.tags),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class HealthAndMetricsFacts:
    actuator_present: bool = False
    health_endpoint_exposed: bool = False
    prometheus_exposed: bool = False
    actuator_endpoints_included: list[str] = field(default_factory=list)
    custom_metrics: list[CustomMetricFact] = field(default_factory=list)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "actuatorPresent": self.actuator_present,
            "healthEndpointExposed": self.health_endpoint_exposed,
            "prometheusExposed": self.prometheus_exposed,
            "actuatorEndpointsIncluded": sorted(self.actuator_endpoints_included),
            "customMetrics": [m.to_dict() for m in sorted(self.custom_metrics, key=lambda x: (x.name, x.metric_type))],
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class DeploymentFacts:
    deployment_name: str | None = None
    container_port: int | str | None = None
    service_port: int | str | None = None
    replica_count: int | str | None = None
    cpu_request: str | None = None
    cpu_limit: str | None = None
    memory_request: str | None = None
    memory_limit: str | None = None
    health_probe_path: str | None = None
    readiness_probe_path: str | None = None
    liveness_probe_path: str | None = None
    descriptor_type: str = "UNKNOWN"  # HELM, KUBERNETES, DOCKERFILE, UNKNOWN
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deploymentName": self.deployment_name,
            "containerPort": self.container_port,
            "servicePort": self.service_port,
            "replicaCount": self.replica_count,
            "cpuRequest": self.cpu_request,
            "cpuLimit": self.cpu_limit,
            "memoryRequest": self.memory_request,
            "memoryLimit": self.memory_limit,
            "healthProbePath": self.health_probe_path,
            "readinessProbePath": self.readiness_probe_path,
            "livenessProbePath": self.liveness_probe_path,
            "descriptorType": self.descriptor_type,
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass(frozen=True)
class ScanManifest:
    status: str  # COMPLETE, PARTIAL
    files_considered: int = 0
    files_read: int = 0
    files_ignored: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "filesConsidered": self.files_considered,
            "filesRead": self.files_read,
            "filesIgnored": self.files_ignored,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ServiceFacts:
    schema_version: str
    service: ServiceMeta
    build: BuildFacts
    apis: list[ApiEndpoint] = field(default_factory=list)
    validation_rules: list[ValidationRule] = field(default_factory=list)
    configuration: list[ConfigEntry] = field(default_factory=list)
    kafka: KafkaFacts = field(default_factory=KafkaFacts)
    datastores: DatastoreFacts = field(default_factory=DatastoreFacts)
    downstream_dependencies: list[DownstreamDependencyFact] = field(default_factory=list)
    health_and_metrics: HealthAndMetricsFacts = field(default_factory=HealthAndMetricsFacts)
    deployment: DeploymentFacts = field(default_factory=DeploymentFacts)
    scan: ScanManifest = field(default_factory=lambda: ScanManifest(status="COMPLETE"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "service": self.service.to_dict(),
            "build": self.build.to_dict(),
            "apis": [a.to_dict() for a in sorted(self.apis, key=lambda x: (x.path, x.http_method))],
            "validationRules": [v.to_dict() for v in sorted(self.validation_rules, key=lambda x: (x.dto_class, x.field_name, x.annotation))],
            "configuration": [c.to_dict() for c in sorted(self.configuration, key=lambda x: (x.property_key, x.profile or ""))],
            "kafka": self.kafka.to_dict(),
            "datastores": self.datastores.to_dict(),
            "downstreamDependencies": [d.to_dict() for d in sorted(self.downstream_dependencies, key=lambda x: (x.client_type, x.client_name or "", x.base_url or ""))],
            "healthAndMetrics": self.health_and_metrics.to_dict(),
            "deployment": self.deployment.to_dict(),
            "scan": self.scan.to_dict(),
        }
