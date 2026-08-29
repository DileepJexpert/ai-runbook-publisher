"""Kafka consumer, producer, and retry/DLT fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

from .config_extractor import parse_placeholder
from .java_parser import JavaAnnotation, JavaClass, JavaParsedFile
from .models import KafkaConsumerFact, KafkaFacts, KafkaProducerFact, SourceEvidence

LOGGER = logging.getLogger(__name__)


def _extract_retry_structure(annotations: list[JavaAnnotation]) -> dict[str, Any] | None:
    """Extract structural retry configuration from @RetryableTopic."""
    for anno in annotations:
        if anno.name == "RetryableTopic":
            attrs = dict(anno.attributes)
            return {
                "configured": True,
                "attempts": attrs.get("attempts"),
                "backoff": attrs.get("backoff"),
                "dltTopicSuffix": attrs.get("dltTopicSuffix"),
                "autoCreateTopics": attrs.get("autoCreateTopics"),
            }
    return None


class KafkaExtractor:
    """Extracts Kafka consumers (@KafkaListener) and producers (KafkaTemplate)."""

    def extract(self, parsed_files: list[JavaParsedFile]) -> KafkaFacts:
        consumers: list[KafkaConsumerFact] = []
        producers: list[KafkaProducerFact] = []

        for pfile in parsed_files:
            for cls in pfile.classes:
                # Map class fields annotated with @Value to identify topic variables
                field_config_map: dict[str, tuple[str, str | None]] = {}
                for field in cls.fields:
                    for a in field.annotations:
                        if a.name == "Value":
                            v_raw = a.get_attr("value")
                            if v_raw:
                                c_key, c_def, is_ph = parse_placeholder(v_raw)
                                if is_ph and c_key:
                                    field_config_map[field.name] = (c_key, c_def)

                # Extract Consumers
                for method in cls.methods:
                    for anno in method.annotations:
                        if anno.name == "KafkaListener":
                            fact = self._parse_kafka_listener(pfile.file_path, cls.name, method.name, anno, method.annotations)
                            consumers.append(fact)

                # Extract Producers
                for method in cls.methods:
                    m_producers = self._scan_producers_in_method(pfile.file_path, cls, method, field_config_map)
                    producers.extend(m_producers)

        return KafkaFacts(consumers=consumers, producers=producers)

    def _parse_kafka_listener(
        self,
        file_path: str,
        class_name: str,
        method_name: str,
        anno: JavaAnnotation,
        all_method_annos: list[JavaAnnotation],
    ) -> KafkaConsumerFact:
        attrs = anno.attributes
        raw_topics = attrs.get("topics") or attrs.get("value") or attrs.get("topicPattern")
        raw_group = attrs.get("groupId") or attrs.get("id")
        concurrency = str(attrs.get("concurrency")) if attrs.get("concurrency") is not None else None
        container_factory = str(attrs.get("containerFactory")) if attrs.get("containerFactory") is not None else None

        topic_expr = str(raw_topics) if raw_topics is not None else None
        group_expr = str(raw_group) if raw_group is not None else None

        # Parse topic placeholder / literal
        topic_config_key, topic_default, topic_is_ph = parse_placeholder(raw_topics)
        topic_literal = str(raw_topics).strip('"\'') if (raw_topics is not None and not topic_is_ph) else None

        # Parse group placeholder / literal
        group_config_key, group_default, group_is_ph = parse_placeholder(raw_group)
        group_literal = str(raw_group).strip('"\'') if (raw_group is not None and not group_is_ph) else None

        status = "CHECK_CONFIG_PORTAL" if (topic_is_ph or group_is_ph) else "KNOWN_FROM_REPOSITORY"

        retry_struct = _extract_retry_structure(all_method_annos)

        evidence = SourceEvidence(
            file=file_path,
            line_start=anno.line_start,
            line_end=anno.line_end,
        )

        return KafkaConsumerFact(
            listener_class=class_name,
            listener_method=method_name,
            topic_expression=topic_expr,
            topic_literal=topic_literal,
            topic_config_key=topic_config_key,
            topic_default=topic_default,
            group_expression=group_expr,
            group_literal=group_literal,
            group_config_key=group_config_key,
            group_default=group_default,
            concurrency=concurrency,
            container_factory=container_factory,
            status=status,
            retry_structure=retry_struct,
            evidence=evidence,
        )

    def _scan_producers_in_method(
        self,
        file_path: str,
        cls: JavaClass,
        method: Any,
        field_config_map: dict[str, tuple[str, str | None]],
    ) -> list[KafkaProducerFact]:
        producers: list[KafkaProducerFact] = []
        body = method.body or ""

        # Match kafkaTemplate.send(topic, ...) or kafkaTemplate.sendDefault(...)
        send_patterns = re.finditer(
            r"""(?:\w+Template|\bkafkaTemplate)\s*\.\s*(send|sendDefault)\s*\(([^)]+)\)""",
            body,
        )

        for match in send_patterns:
            call_type = match.group(1)
            args_str = match.group(2).strip()
            args = [a.strip() for a in args_str.split(",")]

            line_offset = method.line_start + body[: match.start()].count("\n")
            evidence = SourceEvidence(file=file_path, line_start=line_offset, line_end=line_offset)

            if call_type == "sendDefault":
                producers.append(
                    KafkaProducerFact(
                        caller_class=cls.name,
                        caller_method=method.name,
                        resolution="RESOLVED_CONFIG",
                        symbolic_reference="defaultTopic",
                        evidence=evidence,
                    )
                )
                continue

            first_arg = args[0] if args else ""
            if first_arg.startswith('"') and first_arg.endswith('"'):
                # String literal
                literal = first_arg[1:-1]
                producers.append(
                    KafkaProducerFact(
                        caller_class=cls.name,
                        caller_method=method.name,
                        topic_literal=literal,
                        resolution="RESOLVED_LITERAL",
                        evidence=evidence,
                    )
                )
            elif first_arg in field_config_map:
                c_key, c_def = field_config_map[first_arg]
                producers.append(
                    KafkaProducerFact(
                        caller_class=cls.name,
                        caller_method=method.name,
                        topic_config_key=c_key,
                        topic_default=c_def,
                        resolution="RESOLVED_CONFIG",
                        symbolic_reference=first_arg,
                        evidence=evidence,
                    )
                )
            else:
                # Unresolved variable/method call -> do not guess!
                producers.append(
                    KafkaProducerFact(
                        caller_class=cls.name,
                        caller_method=method.name,
                        resolution="UNRESOLVED_REPOSITORY_EXPRESSION",
                        symbolic_reference=first_arg if first_arg else None,
                        evidence=evidence,
                    )
                )

        return producers
