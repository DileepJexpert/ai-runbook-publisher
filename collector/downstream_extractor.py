"""Downstream HTTP dependency and resilience fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

from .config_extractor import ConfigEntry, parse_placeholder
from .java_parser import JavaAnnotation, JavaClass, JavaParsedFile
from .models import DownstreamDependencyFact, ResilienceFact, SourceEvidence

LOGGER = logging.getLogger(__name__)

RESILIENCE_ANNOTATIONS = {
    "CircuitBreaker": "CIRCUIT_BREAKER",
    "Retry": "RETRY",
    "RateLimiter": "RATE_LIMITER",
    "Bulkhead": "BULKHEAD",
    "TimeLimiter": "TIME_LIMITER",
}


class DownstreamExtractor:
    """Extracts Feign clients, RestClient, RestTemplate, WebClient, and Resilience4j configurations."""

    def extract(self, parsed_files: list[JavaParsedFile], config_entries: list[ConfigEntry] | None = None) -> list[DownstreamDependencyFact]:
        clients: list[DownstreamDependencyFact] = []

        # 1. Extract Feign Clients
        for pfile in parsed_files:
            for cls in pfile.classes:
                for anno in cls.annotations:
                    if anno.name == "FeignClient":
                        fact = self._extract_feign_client(pfile.file_path, cls, anno)
                        clients.append(fact)

        # 2. Extract RestClient / RestTemplate / WebClient usages
        for pfile in parsed_files:
            for cls in pfile.classes:
                # Check for RestClient / RestTemplate / WebClient fields or beans
                other_clients = self._extract_programmatic_clients(pfile.file_path, cls)
                clients.extend(other_clients)

        # 3. Associate Resilience facts from annotations or config entries
        self._enrich_resilience_from_annotations(parsed_files, clients)
        if config_entries:
            self._enrich_resilience_from_config(config_entries, clients)

        return clients

    def _extract_feign_client(self, file_path: str, cls: JavaClass, anno: JavaAnnotation) -> DownstreamDependencyFact:
        attrs = anno.attributes
        name = attrs.get("name") or attrs.get("value") or attrs.get("serviceId")
        raw_url = attrs.get("url")

        client_name = str(name).strip('"\'') if name else cls.name

        base_url = None
        url_config_key = None
        url_default = None

        if raw_url:
            c_key, c_def, is_ph = parse_placeholder(raw_url)
            if is_ph:
                url_config_key = c_key
                url_default = c_def
            else:
                base_url = str(raw_url).strip('"\'')

        evidence = SourceEvidence(file=file_path, line_start=anno.line_start, line_end=cls.line_end)

        return DownstreamDependencyFact(
            client_type="FEIGN",
            client_name=client_name,
            base_url=base_url,
            url_config_key=url_config_key,
            url_default=url_default,
            evidence=evidence,
        )

    def _extract_programmatic_clients(self, file_path: str, cls: JavaClass) -> list[DownstreamDependencyFact]:
        results: list[DownstreamDependencyFact] = []

        # Check fields for RestClient, RestTemplate, WebClient
        for field in cls.fields:
            c_type = None
            if "RestClient" in field.field_type:
                c_type = "REST_CLIENT"
            elif "RestTemplate" in field.field_type:
                c_type = "REST_TEMPLATE"
            elif "WebClient" in field.field_type:
                c_type = "WEB_CLIENT"

            if c_type:
                # Look for companion @Value on field or in class
                url_config_key = None
                url_default = None
                for a in field.annotations:
                    if a.name == "Value":
                        v_raw = a.get_attr("value")
                        if v_raw:
                            c_k, c_d, is_ph = parse_placeholder(v_raw)
                            if is_ph:
                                url_config_key = c_k
                                url_default = c_d

                evidence = SourceEvidence(file=file_path, line_start=field.line_start, line_end=field.line_end)
                results.append(
                    DownstreamDependencyFact(
                        client_type=c_type,
                        client_name=field.name,
                        url_config_key=url_config_key,
                        url_default=url_default,
                        evidence=evidence,
                    )
                )

        return results

    def _enrich_resilience_from_annotations(self, parsed_files: list[JavaParsedFile], clients: list[DownstreamDependencyFact]) -> None:
        for pfile in parsed_files:
            for cls in pfile.classes:
                all_annos = list(cls.annotations)
                for method in cls.methods:
                    all_annos.extend(method.annotations)

                for a in all_annos:
                    if a.name in RESILIENCE_ANNOTATIONS:
                        res_type = RESILIENCE_ANNOTATIONS[a.name]
                        r_name = str(a.get_attr("name") or a.get_attr("value") or cls.name).strip('"\'')
                        evidence = SourceEvidence(file=pfile.file_path, line_start=a.line_start, line_end=a.line_end)
                        fact = ResilienceFact(
                            type=res_type,
                            name=r_name,
                            target_component=cls.name,
                            evidence=evidence,
                        )
                        # Match with client if name matches
                        matched = False
                        for client in clients:
                            if client.client_name and (client.client_name.lower() in r_name.lower() or r_name.lower() in client.client_name.lower()):
                                client.resilience.append(fact)
                                matched = True
                                break
                        if not matched and clients:
                            clients[0].resilience.append(fact)

    def _enrich_resilience_from_config(self, config_entries: list[ConfigEntry], clients: list[DownstreamDependencyFact]) -> None:
        for entry in config_entries:
            k = entry.property_key
            if "resilience4j." in k:
                # e.g. resilience4j.retry.instances.cbsClient.maxAttempts: 3
                retry_match = re.match(r"resilience4j\.retry\.instances\.([A-Za-z0-9_-]+)\.maxAttempts", k)
                if retry_match:
                    r_name = retry_match.group(1)
                    attempts = int(entry.repository_value) if (entry.repository_value and str(entry.repository_value).isdigit()) else None
                    fact = ResilienceFact(
                        type="RETRY",
                        name=r_name,
                        max_attempts=attempts,
                        property_key=k,
                        config_key=entry.config_key,
                        evidence=entry.evidence,
                    )
                    for client in clients:
                        if client.client_name and (client.client_name.lower() in r_name.lower() or r_name.lower() in client.client_name.lower()):
                            client.resilience.append(fact)
                            break
