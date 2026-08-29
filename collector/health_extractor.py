"""Health, Actuator, and Micrometer metrics fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

from .build_extractor import BuildFacts
from .config_extractor import ConfigEntry
from .java_parser import JavaParsedFile
from .models import CustomMetricFact, HealthAndMetricsFacts, SourceEvidence

LOGGER = logging.getLogger(__name__)


class HealthExtractor:
    """Extracts Actuator exposure and custom Micrometer metrics."""

    def extract(
        self,
        build_facts: BuildFacts,
        config_entries: list[ConfigEntry],
        parsed_files: list[JavaParsedFile],
    ) -> HealthAndMetricsFacts:
        actuator_present = "Actuator" in build_facts.detected_dependencies
        health_exposed = False
        prometheus_exposed = "Prometheus registry" in build_facts.detected_dependencies
        endpoints_included: list[str] = []

        # Analyze configuration for actuator endpoints
        for entry in config_entries:
            k = entry.property_key.lower()
            val = str(entry.repository_value or entry.repository_default or "").lower()

            if "management.endpoints.web.exposure.include" in k:
                actuator_present = True
                items = [i.strip() for i in val.split(",") if i.strip()]
                endpoints_included.extend(items)
                if "*" in items or "health" in items:
                    health_exposed = True
                if "*" in items or "prometheus" in items:
                    prometheus_exposed = True

            if "management.endpoint.health.enabled" in k:
                if val == "true":
                    health_exposed = True

            if "management.endpoint.prometheus.enabled" in k:
                if val == "true":
                    prometheus_exposed = True

        # Scan Java files for custom metrics
        custom_metrics = self._scan_custom_metrics(parsed_files)

        return HealthAndMetricsFacts(
            actuator_present=actuator_present,
            health_endpoint_exposed=health_exposed or actuator_present,
            prometheus_exposed=prometheus_exposed,
            actuator_endpoints_included=sorted(list(set(endpoints_included))),
            custom_metrics=custom_metrics,
        )

    def _scan_custom_metrics(self, parsed_files: list[JavaParsedFile]) -> list[CustomMetricFact]:
        metrics: list[CustomMetricFact] = []

        # Match Counter.builder("metric.name"), Timer.builder("..."), Gauge.builder("..."), meterRegistry.counter("...")
        builder_regex = re.compile(
            r"""\b(Counter|Timer|Gauge|DistributionSummary)\s*\.\s*builder\s*\(\s*['"]([^'"]+)['"]""",
            re.MULTILINE,
        )

        registry_regex = re.compile(
            r"""\bmeterRegistry\s*\.\s*(counter|timer|gauge)\s*\(\s*['"]([^'"]+)['"]""",
            re.MULTILINE,
        )

        for pfile in parsed_files:
            for cls in pfile.classes:
                for method in cls.methods:
                    body = method.body or ""

                    # Builders
                    for match in builder_regex.finditer(body):
                        m_type = match.group(1).upper()
                        m_name = match.group(2)
                        line_offset = method.line_start + body[: match.start()].count("\n")
                        evidence = SourceEvidence(file=pfile.file_path, line_start=line_offset, line_end=line_offset)
                        metrics.append(
                            CustomMetricFact(
                                name=m_name,
                                metric_type=m_type,
                                evidence=evidence,
                            )
                        )

                    # Registry direct calls
                    for match in registry_regex.finditer(body):
                        m_type = match.group(1).upper()
                        m_name = match.group(2)
                        line_offset = method.line_start + body[: match.start()].count("\n")
                        evidence = SourceEvidence(file=pfile.file_path, line_start=line_offset, line_end=line_offset)
                        metrics.append(
                            CustomMetricFact(
                                name=m_name,
                                metric_type=m_type,
                                evidence=evidence,
                            )
                        )

        return metrics
