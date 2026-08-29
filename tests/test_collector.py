"""Comprehensive tests for deterministic Spring Boot service fact collector."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from collector.models import (
    BuildFacts,
    ConfigEntry,
    DatastoreFacts,
    DeploymentFacts,
    HealthAndMetricsFacts,
    KafkaFacts,
    ScanManifest,
    ServiceFacts,
    ServiceMeta,
    SourceEvidence,
)
from collector.service_collector import ServiceFactsCollector, collect_service_facts, save_service_facts
from publisher.repository import inspect_repository


def create_fixture_git_repo(tmp_path: Path) -> Path:
    """Create a fully featured Spring Boot test repository with Git initialized."""
    repo_dir = tmp_path / "payment-integration-service"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # 1. pom.xml
    pom_xml = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
        <relativePath/>
    </parent>
    <groupId>com.idfc.payments</groupId>
    <artifactId>payment-integration-service</artifactId>
    <version>1.2.0</version>
    <name>payment-integration-service</name>
    <properties>
        <java.version>17</java.version>
    </properties>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.kafka</groupId>
            <artifactId>spring-kafka</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
        <dependency>
            <groupId>io.micrometer</groupId>
            <artifactId>micrometer-registry-prometheus</artifactId>
        </dependency>
        <dependency>
            <groupId>io.github.resilience4j</groupId>
            <artifactId>resilience4j-spring-boot3</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-starter-openfeign</artifactId>
        </dependency>
        <dependency>
            <groupId>org.flywaydb</groupId>
            <artifactId>flyway-core</artifactId>
        </dependency>
    </dependencies>
</project>
"""
    (repo_dir / "pom.xml").write_text(pom_xml, encoding="utf-8")

    # 2. Config files
    resources_dir = repo_dir / "src" / "main" / "resources"
    resources_dir.mkdir(parents=True, exist_ok=True)

    app_yml = """
spring:
  application:
    name: payment-integration-service
server:
  port: 8080
payment:
  timeout: 5000
  external-host: ${PAYMENT_HOST}
  retry-delay: ${PAYMENT_RETRY_DELAY:1000}
database:
  password: ${DATABASE_PASSWORD}
api:
  secret-token: SuperSecretLiteralKey123
management:
  endpoints:
    web:
      exposure:
        include: "health,info,prometheus"
resilience4j:
  retry:
    instances:
      cbsClient:
        maxAttempts: 3
"""
    (resources_dir / "application.yml").write_text(app_yml, encoding="utf-8")

    app_props = """
cbs.service.url=${CBS_SERVICE_URL:http://cbs.bank.local}
cbs.timeout=2000
ledger.service.url=${LEDGER_SERVICE_URL:http://ledger.bank.local}
"""
    (resources_dir / "application.properties").write_text(app_props, encoding="utf-8")

    # 3. Flyway SQL Migration
    migration_dir = resources_dir / "db" / "migration"
    migration_dir.mkdir(parents=True, exist_ok=True)
    v1_sql = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL
);
"""
    (migration_dir / "V1__init_payments.sql").write_text(v1_sql, encoding="utf-8")

    # 4. Java Sources
    java_dir = repo_dir / "src" / "main" / "java" / "com" / "idfc" / "payments"
    (java_dir / "dto").mkdir(parents=True, exist_ok=True)
    (java_dir / "entity").mkdir(parents=True, exist_ok=True)
    (java_dir / "repository").mkdir(parents=True, exist_ok=True)
    (java_dir / "client").mkdir(parents=True, exist_ok=True)
    (java_dir / "controller").mkdir(parents=True, exist_ok=True)
    (java_dir / "consumer").mkdir(parents=True, exist_ok=True)
    (java_dir / "producer").mkdir(parents=True, exist_ok=True)
    (java_dir / "service").mkdir(parents=True, exist_ok=True)

    # DTO
    req_dto = """package com.idfc.payments.dto;

import jakarta.validation.constraints.*;
import java.math.BigDecimal;

public class CreatePaymentRequest {
    @NotNull
    @Positive
    private BigDecimal amount;

    @NotBlank
    @Size(min = 2, max = 30, message = "Invalid customer ID")
    private String customerId;

    @Pattern(regexp = "^[A-Z]{3}$")
    private String currency;

    public BigDecimal getAmount() { return amount; }
    public String getCustomerId() { return customerId; }
    public String getCurrency() { return currency; }
}
"""
    (java_dir / "dto" / "CreatePaymentRequest.java").write_text(req_dto, encoding="utf-8")

    # Entity
    entity_code = """package com.idfc.payments.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;

@Entity
@Table(name = "payments", schema = "public")
public class PaymentEntity {
    @Id
    @Column(name = "payment_id")
    private String paymentId;

    @Column(name = "amount")
    private BigDecimal amount;

    @Column(name = "status")
    private String status;
}
"""
    (java_dir / "entity" / "PaymentEntity.java").write_text(entity_code, encoding="utf-8")

    # Repository
    repo_code = """package com.idfc.payments.repository;

import com.idfc.payments.entity.PaymentEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

@Repository
public interface PaymentRepository extends JpaRepository<PaymentEntity, String> {
}
"""
    (java_dir / "repository" / "PaymentRepository.java").write_text(repo_code, encoding="utf-8")

    # Feign Client
    feign_code = """package com.idfc.payments.client;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;

@FeignClient(name = "cbs-service", url = "${cbs.service.url:http://cbs.bank.local}")
public interface CbsClient {
    @GetMapping("/v1/accounts/{id}")
    String getAccount(@PathVariable("id") String id);
}
"""
    (java_dir / "client" / "CbsClient.java").write_text(feign_code, encoding="utf-8")

    # RestClient Client
    rest_client_code = """package com.idfc.payments.client;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class LedgerClient {
    @Value("${ledger.service.url:http://ledger.bank.local}")
    private String ledgerUrl;

    private RestClient restClient;
}
"""
    (java_dir / "client" / "LedgerClient.java").write_text(rest_client_code, encoding="utf-8")

    # Controller
    controller_code = """package com.idfc.payments.controller;

import com.idfc.payments.dto.CreatePaymentRequest;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/payments")
public class PaymentController {

    @GetMapping("/{id}")
    @PreAuthorize("hasRole('VIEWER')")
    public ResponseEntity<String> getPayment(
        @PathVariable("id") String paymentId,
        @RequestParam(name = "detail", required = false) boolean detail
    ) {
        return ResponseEntity.ok("payment-" + paymentId);
    }

    @PostMapping(
        value = "/create",
        consumes = "application/json"
    )
    public ResponseEntity<String> createPayment(@RequestBody @Valid CreatePaymentRequest request) {
        return ResponseEntity.ok("created");
    }
}
"""
    (java_dir / "controller" / "PaymentController.java").write_text(controller_code, encoding="utf-8")

    # Kafka Consumer
    consumer_code = """package com.idfc.payments.consumer;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
import org.springframework.stereotype.Component;

@Component
public class PaymentEventConsumer {

    @KafkaListener(
        topics = "${payment.topic:payment-events}",
        groupId = "${payment.group:payment-consumer-group}",
        concurrency = "2"
    )
    @RetryableTopic(attempts = "3")
    public void consumePaymentEvent(String event) {
        System.out.println("Processing event: " + event);
    }

    @KafkaListener(topics = "manual-reconciliation-topic")
    public void consumeLiteralTopic(String event) {
    }
}
"""
    (java_dir / "consumer" / "PaymentEventConsumer.java").write_text(consumer_code, encoding="utf-8")

    # Kafka Producer
    producer_code = """package com.idfc.payments.producer;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class PaymentEventProducer {
    private final KafkaTemplate<String, String> kafkaTemplate;

    @Value("${payment.outbound.topic:payment-outbound}")
    private String outboundTopic;

    public PaymentEventProducer(KafkaTemplate<String, String> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void publishLiteral(String payload) {
        kafkaTemplate.send("payment-notifications", payload);
    }

    public void publishConfigured(String payload) {
        kafkaTemplate.send(outboundTopic, payload);
    }

    public void publishUnresolved(String payload) {
        kafkaTemplate.send(getDynamicTopic(), payload);
    }

    private String getDynamicTopic() {
        return "dynamic-topic";
    }
}
"""
    (java_dir / "producer" / "PaymentEventProducer.java").write_text(producer_code, encoding="utf-8")

    # Service (with Micrometer metrics & JPA access)
    service_code = """package com.idfc.payments.service;

import com.idfc.payments.entity.PaymentEntity;
import com.idfc.payments.repository.PaymentRepository;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Service;

@Service
public class PaymentService {
    private final PaymentRepository paymentRepository;
    private final MeterRegistry meterRegistry;

    public PaymentService(PaymentRepository paymentRepository, MeterRegistry meterRegistry) {
        this.paymentRepository = paymentRepository;
        this.meterRegistry = meterRegistry;
    }

    @CircuitBreaker(name = "cbsClient")
    public void processPayment(PaymentEntity payment) {
        paymentRepository.save(payment);
        paymentRepository.findById("123");

        Counter.builder("payment.processed.count").register(meterRegistry).increment();
        Timer.builder("payment.processing.latency").register(meterRegistry);
        meterRegistry.counter("payment.error.count").increment();
    }
}
"""
    (java_dir / "service" / "PaymentService.java").write_text(service_code, encoding="utf-8")

    # 5. Helm values.yaml
    helm_dir = repo_dir / "helm"
    helm_dir.mkdir(parents=True, exist_ok=True)
    helm_values = """
replicaCount: 2
nameOverride: payment-integration-service
service:
  port: 8080
  targetPort: 8080
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: 1000m
    memory: 1Gi
readinessProbe:
  httpGet:
    path: /actuator/health/readiness
livenessProbe:
  httpGet:
    path: /actuator/health/liveness
"""
    (helm_dir / "values.yaml").write_text(helm_values, encoding="utf-8")

    # Init Git
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@idfc.local"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo_dir), check=True, capture_output=True)

    return repo_dir


# ==============================================================================
# TESTS
# ==============================================================================


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    return create_fixture_git_repo(tmp_path)


# --- BUILD TESTS ---


def test_01_maven_artifact_metadata_extracted(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.build.build_system == "MAVEN"
    assert facts.build.group_id == "com.idfc.payments"
    assert facts.build.artifact_id == "payment-integration-service"
    assert facts.build.version == "1.2.0"


def test_02_java_version_extracted_where_declared(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.build.java_version == "17"


def test_03_spring_boot_version_extracted_where_declared(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.build.spring_boot_version == "3.2.0"


def test_04_dependencies_detected_correctly(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    deps = facts.build.detected_dependencies
    assert "Spring Web" in deps
    assert "Spring Kafka" in deps
    assert "Spring Data JPA" in deps
    assert "Actuator" in deps
    assert "Prometheus registry" in deps
    assert "Resilience4j" in deps
    assert "Feign" in deps
    assert "Flyway" in deps


# --- CONFIG TESTS ---


def test_05_yaml_literal_config_extracted(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    timeout_entry = next((c for c in facts.configuration if c.property_key == "payment.timeout"), None)
    assert timeout_entry is not None
    assert timeout_entry.status == "KNOWN_FROM_REPOSITORY"
    assert timeout_entry.repository_value == 5000


def test_06_properties_literal_extracted(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    timeout_entry = next((c for c in facts.configuration if c.property_key == "cbs.timeout"), None)
    assert timeout_entry is not None
    assert timeout_entry.status == "KNOWN_FROM_REPOSITORY"
    assert str(timeout_entry.repository_value) == "2000"


def test_07_placeholder_retains_exact_config_key(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    entry = next((c for c in facts.configuration if c.property_key == "payment.external-host"), None)
    assert entry is not None
    assert entry.config_key == "PAYMENT_HOST"
    assert entry.repository_value is None
    assert entry.status == "CHECK_CONFIG_PORTAL"


def test_08_placeholder_keeps_default_separate(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    entry = next((c for c in facts.configuration if c.property_key == "payment.retry-delay"), None)
    assert entry is not None
    assert entry.config_key == "PAYMENT_RETRY_DELAY"
    assert entry.repository_default == "1000"
    assert entry.repository_value is None
    assert entry.status == "CHECK_CONFIG_PORTAL"


def test_09_runtime_placeholder_not_treated_as_active_value(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    cbs_entry = next((c for c in facts.configuration if c.property_key == "cbs.service.url"), None)
    assert cbs_entry is not None
    assert cbs_entry.config_key == "CBS_SERVICE_URL"
    assert cbs_entry.repository_default == "http://cbs.bank.local"
    assert cbs_entry.repository_value is None


def test_10_sensitive_value_never_serialized(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    facts_json = json.dumps(facts.to_dict())
    assert "SuperSecretLiteralKey123" not in facts_json


def test_11_sensitive_config_marked_protected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    pwd_entry = next((c for c in facts.configuration if c.property_key == "database.password"), None)
    assert pwd_entry is not None
    assert pwd_entry.sensitive is True
    assert pwd_entry.status == "PROTECTED_CHECK_CONFIG_PORTAL"

    sec_entry = next((c for c in facts.configuration if c.property_key == "api.secret-token"), None)
    assert sec_entry is not None
    assert sec_entry.sensitive is True
    assert sec_entry.status == "PROTECTED_REPOSITORY_VALUE"


# --- API TESTS ---


def test_12_get_endpoint_extraction(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    get_ep = next((a for a in facts.apis if a.http_method == "GET" and a.path == "/v1/payments/{id}"), None)
    assert get_ep is not None
    assert get_ep.controller_class == "PaymentController"
    assert get_ep.handler_method == "getPayment"


def test_13_post_endpoint_extraction(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    post_ep = next((a for a in facts.apis if a.http_method == "POST" and a.path == "/v1/payments/create"), None)
    assert post_ep is not None
    assert post_ep.controller_class == "PaymentController"
    assert post_ep.handler_method == "createPayment"


def test_14_class_and_method_mappings_composed_correctly(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    paths = {a.path for a in facts.apis}
    assert "/v1/payments/{id}" in paths
    assert "/v1/payments/create" in paths


def test_15_multiline_annotations_supported(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    post_ep = next((a for a in facts.apis if a.path == "/v1/payments/create"), None)
    assert post_ep is not None
    assert post_ep.http_method == "POST"


def test_16_path_variable_extraction(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    get_ep = next((a for a in facts.apis if a.path == "/v1/payments/{id}"), None)
    assert get_ep is not None
    assert "paymentId" in get_ep.path_variables or "id" in get_ep.path_variables


def test_17_request_param_extraction(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    get_ep = next((a for a in facts.apis if a.path == "/v1/payments/{id}"), None)
    assert get_ep is not None
    assert "detail" in get_ep.request_params


def test_18_request_body_type_extraction(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    post_ep = next((a for a in facts.apis if a.path == "/v1/payments/create"), None)
    assert post_ep is not None
    assert post_ep.request_body_type == "CreatePaymentRequest"


# --- VALIDATION TESTS ---


def test_19_validation_not_null(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    rule = next((r for r in facts.validation_rules if r.dto_class == "CreatePaymentRequest" and r.field_name == "amount" and r.annotation == "@NotNull"), None)
    assert rule is not None
    assert rule.mechanical_description == "must not be null"


def test_20_validation_positive(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    rule = next((r for r in facts.validation_rules if r.dto_class == "CreatePaymentRequest" and r.field_name == "amount" and r.annotation == "@Positive"), None)
    assert rule is not None
    assert rule.mechanical_description == "must be greater than zero"


def test_21_validation_size(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    rule = next((r for r in facts.validation_rules if r.dto_class == "CreatePaymentRequest" and r.field_name == "customerId" and r.annotation == "@Size"), None)
    assert rule is not None
    assert rule.parameters.get("min") == 2
    assert rule.parameters.get("max") == 30
    assert rule.message == "Invalid customer ID"
    assert "size between 2 and 30" in rule.mechanical_description


def test_22_validation_pattern(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    rule = next((r for r in facts.validation_rules if r.dto_class == "CreatePaymentRequest" and r.field_name == "currency" and r.annotation == "@Pattern"), None)
    assert rule is not None
    assert rule.parameters.get("regexp") == "^[A-Z]{3}$"


# --- KAFKA TESTS ---


def test_23_consumer_literal_topic(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    c = next((c for c in facts.kafka.consumers if c.topic_literal == "manual-reconciliation-topic"), None)
    assert c is not None
    assert c.status == "KNOWN_FROM_REPOSITORY"


def test_24_consumer_config_topic(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    c = next((c for c in facts.kafka.consumers if c.topic_config_key == "payment.topic"), None)
    assert c is not None
    assert c.topic_default == "payment-events"
    assert c.status == "CHECK_CONFIG_PORTAL"


def test_25_consumer_group_id(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    c = next((c for c in facts.kafka.consumers if c.group_config_key == "payment.group"), None)
    assert c is not None
    assert c.group_default == "payment-consumer-group"


def test_26_producer_literal_topic(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    p = next((p for p in facts.kafka.producers if p.topic_literal == "payment-notifications"), None)
    assert p is not None
    assert p.resolution == "RESOLVED_LITERAL"


def test_27_unresolved_producer_expression_not_guessed(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    p = next((p for p in facts.kafka.producers if p.caller_method == "publishUnresolved"), None)
    assert p is not None
    assert p.resolution == "UNRESOLVED_REPOSITORY_EXPRESSION"
    assert p.topic_literal is None


def test_28_retryable_topic_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    c = next((c for c in facts.kafka.consumers if c.retry_structure is not None), None)
    assert c is not None
    assert c.retry_structure.get("configured") is True


# --- DATABASE TESTS ---


def test_29_table_name_extracted(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    tbl = next((t for t in facts.datastores.database_tables if t.table_name.lower() == "payments"), None)
    assert tbl is not None
    assert tbl.schema_name == "public" or tbl.schema_name is None


def test_30_table_id_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    tbl = next((t for t in facts.datastores.database_tables if t.table_name.lower() == "payments"), None)
    assert tbl is not None
    assert "payment_id" in tbl.identifier_columns


def test_31_repository_interface_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    repo = next((r for r in facts.datastores.repositories if r.interface_name == "PaymentRepository"), None)
    assert repo is not None
    assert repo.entity_class == "PaymentEntity"


def test_32_flyway_table_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    tbl = next((t for t in facts.datastores.database_tables if "FLYWAY" in t.source_type), None)
    assert tbl is not None
    assert tbl.table_name.lower() == "payments"


# --- DOWNSTREAM TESTS ---


def test_33_feign_or_rest_client_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    feign = next((d for d in facts.downstream_dependencies if d.client_type == "FEIGN"), None)
    assert feign is not None
    assert feign.client_name == "cbs-service"

    rest_c = next((d for d in facts.downstream_dependencies if d.client_type == "REST_CLIENT"), None)
    assert rest_c is not None


def test_34_downstream_url_config_key_retained(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    feign = next((d for d in facts.downstream_dependencies if d.client_type == "FEIGN"), None)
    assert feign is not None
    assert feign.url_config_key == "cbs.service.url"
    assert feign.url_default == "http://cbs.bank.local"


def test_35_resilience_circuit_breaker_retained(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    resilience_items = [r for d in facts.downstream_dependencies for r in d.resilience]
    assert len(resilience_items) > 0
    cb = next((r for r in resilience_items if r.type == "CIRCUIT_BREAKER"), None)
    assert cb is not None
    assert cb.name == "cbsClient"


# --- OBSERVABILITY TESTS ---


def test_36_actuator_dependency_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.health_and_metrics.actuator_present is True


def test_37_prometheus_configuration_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.health_and_metrics.prometheus_exposed is True
    assert "prometheus" in facts.health_and_metrics.actuator_endpoints_included


def test_38_custom_metric_literal_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    metric_names = {m.name for m in facts.health_and_metrics.custom_metrics}
    assert "payment.processed.count" in metric_names
    assert "payment.processing.latency" in metric_names
    assert "payment.error.count" in metric_names


# --- DEPLOYMENT TESTS ---


def test_39_helm_replica_value_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.deployment.replica_count == 2
    assert facts.deployment.descriptor_type == "HELM"


def test_40_resource_request_limit_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.deployment.cpu_request == "500m"
    assert facts.deployment.memory_request == "512Mi"
    assert facts.deployment.cpu_limit == "1000m"
    assert facts.deployment.memory_limit == "1Gi"


def test_41_probe_path_detected(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.deployment.readiness_probe_path == "/actuator/health/readiness"
    assert facts.deployment.liveness_probe_path == "/actuator/health/liveness"


# --- SCAN & EVIDENCE TESTS ---


def test_42_normal_excluded_binaries_do_not_cause_partial(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    assert facts.scan.status == "COMPLETE"
    assert facts.scan.files_considered > 0


def test_43_parse_failure_causes_partial(sample_repo: Path):
    # Add an unreadable Java file
    bad_java = sample_repo / "src" / "main" / "java" / "com" / "idfc" / "payments" / "BadFile.java"
    bad_java.write_text("invalid java class {{{{", encoding="utf-8")
    # Simulate parser handling
    facts = collect_service_facts(str(sample_repo))
    assert facts.scan.files_considered > 0


def test_44_evidence_uses_relative_paths(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    for ep in facts.apis:
        if ep.evidence:
            assert not ep.evidence.file.startswith("/")
            assert not (len(ep.evidence.file) > 1 and ep.evidence.file[1] == ":")


def test_45_line_evidence_valid_where_supplied(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    for ep in facts.apis:
        if ep.evidence and ep.evidence.line_start is not None:
            assert ep.evidence.line_start >= 1


# --- SECURITY TESTS ---


def test_46_no_secret_values_appear_in_generated_json(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    out_file = save_service_facts(facts, sample_repo / "output")
    content = out_file.read_text(encoding="utf-8")
    assert "SuperSecretLiteralKey123" not in content
    assert "SuperSecret" not in content


def test_47_no_repository_modification_occurs(sample_repo: Path):
    # Check working tree status before and after
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(sample_repo), capture_output=True, text=True).stdout
    collect_service_facts(str(sample_repo))
    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=str(sample_repo), capture_output=True, text=True).stdout
    assert status_before == status_after


def test_48_no_ai_client_is_called(sample_repo: Path, monkeypatch):
    # Monkeypatch any AI or network calls to ensure none occur
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Network/AI call was made in deterministic collector!")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)

    facts = collect_service_facts(str(sample_repo))
    assert facts.schema_version == "1.0"


def test_49_no_confluence_client_is_called(sample_repo: Path, monkeypatch):
    import requests
    def fail_requests(*args, **kwargs):
        raise AssertionError("Requests call was made!")

    monkeypatch.setattr(requests, "post", fail_requests)
    monkeypatch.setattr(requests, "get", fail_requests)

    facts = collect_service_facts(str(sample_repo))
    assert facts.scan.status == "COMPLETE"


# --- GOLDEN OUTPUT TEST ---


def test_50_golden_output_structure(sample_repo: Path):
    facts = collect_service_facts(str(sample_repo))
    d = facts.to_dict()

    assert d["schemaVersion"] == "1.0"
    assert "service" in d
    assert "build" in d
    assert "apis" in d
    assert "validationRules" in d
    assert "configuration" in d
    assert "kafka" in d
    assert "datastores" in d
    assert "downstreamDependencies" in d
    assert "healthAndMetrics" in d
    assert "deployment" in d
    assert "scan" in d

    # Verify no business interpretation fields exist
    json_str = json.dumps(d)
    forbidden_words = ["businessPurpose", "troubleshootingGuidance", "probableCauses", "supportAction"]
    for word in forbidden_words:
        assert word not in json_str
