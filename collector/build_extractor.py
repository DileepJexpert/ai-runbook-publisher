"""Build metadata extractor for Maven and Gradle Spring Boot projects."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from publisher.repository_tools import RepositoryTools

from .models import BuildFacts, SourceEvidence

LOGGER = logging.getLogger(__name__)

DEPENDENCY_MAPPINGS = [
    (r"spring-boot-starter-web(?!flux)", "Spring Web"),
    (r"spring-boot-starter-webflux", "Spring WebFlux"),
    (r"spring-kafka", "Spring Kafka"),
    (r"spring-boot-starter-data-jpa", "Spring Data JPA"),
    (r"spring-boot-starter-data-jdbc", "Spring Data JDBC"),
    (r"spring-boot-starter-data-redis", "Spring Data Redis"),
    (r"spring-boot-starter-actuator", "Actuator"),
    (r"micrometer-registry-prometheus", "Prometheus registry"),
    (r"micrometer-core", "Micrometer"),
    (r"resilience4j", "Resilience4j"),
    (r"(?:spring-cloud-starter-openfeign|feign-core)", "Feign"),
    (r"(?:spring-data-aerospike|aerospike-client)", "Aerospike"),
    (r"flyway-core", "Flyway"),
    (r"liquibase-core", "Liquibase"),
    (r"lombok", "Lombok"),
    (r"spring-security", "Spring Security"),
]


class BuildExtractor:
    """Extracts build system, Java version, Spring Boot version, and key dependencies."""

    def __init__(self, tools: RepositoryTools) -> None:
        self.tools = tools

    def extract(self) -> BuildFacts:
        # Check for pom.xml
        try:
            pom_content = self.tools.read_file("pom.xml")
            return self._extract_maven("pom.xml", pom_content)
        except Exception:
            pass

        # Check for build.gradle.kts
        try:
            gradle_kts = self.tools.read_file("build.gradle.kts")
            return self._extract_gradle("build.gradle.kts", gradle_kts)
        except Exception:
            pass

        # Check for build.gradle
        try:
            gradle_content = self.tools.read_file("build.gradle")
            return self._extract_gradle("build.gradle", gradle_content)
        except Exception:
            pass

        return BuildFacts(build_system="UNKNOWN")

    def _extract_maven(self, file_path: str, content: str) -> BuildFacts:
        lines = content.splitlines()
        total_lines = len(lines)
        evidence = SourceEvidence(file=file_path, line_start=1, line_end=total_lines)

        try:
            # Strip default namespace for clean XPath querying
            clean_xml = re.sub(r'\sxmlns="[^"]+"', "", content, count=1)
            root = ET.fromstring(clean_xml)
        except Exception as exc:
            LOGGER.warning("Failed to parse %s with XML parser: %s", file_path, exc)
            return BuildFacts(build_system="MAVEN", evidence=evidence)

        # Extract groupId
        group_id = None
        group_elem = root.find("groupId")
        if group_elem is not None and group_elem.text:
            group_id = group_elem.text.strip()
        else:
            parent_group = root.find("parent/groupId")
            if parent_group is not None and parent_group.text:
                group_id = parent_group.text.strip()

        # Extract artifactId
        artifact_id = None
        art_elem = root.find("artifactId")
        if art_elem is not None and art_elem.text:
            artifact_id = art_elem.text.strip()

        # Extract version
        version = None
        ver_elem = root.find("version")
        if ver_elem is not None and ver_elem.text:
            version = ver_elem.text.strip()
        else:
            parent_ver = root.find("parent/version")
            if parent_ver is not None and parent_ver.text:
                version = parent_ver.text.strip()

        # Extract Java version
        java_version = None
        prop_java = root.find("properties/java.version")
        if prop_java is not None and prop_java.text:
            java_version = prop_java.text.strip()
        if not java_version:
            comp_source = root.find("properties/maven.compiler.source")
            if comp_source is not None and comp_source.text:
                java_version = comp_source.text.strip()
        if not java_version:
            comp_release = root.find("properties/maven.compiler.release")
            if comp_release is not None and comp_release.text:
                java_version = comp_release.text.strip()

        # Extract Spring Boot version
        spring_boot_version = None
        parent_art = root.find("parent/artifactId")
        if parent_art is not None and parent_art.text in {"spring-boot-starter-parent", "spring-boot-dependencies"}:
            parent_ver = root.find("parent/version")
            if parent_ver is not None and parent_ver.text:
                spring_boot_version = parent_ver.text.strip()

        if not spring_boot_version:
            boot_prop = root.find("properties/spring-boot.version") or root.find("properties/spring.boot.version")
            if boot_prop is not None and boot_prop.text:
                spring_boot_version = boot_prop.text.strip()

        # Extract detected dependencies
        detected_deps = set()
        for dep in root.findall(".//dependency"):
            art = dep.find("artifactId")
            art_text = art.text.strip() if art is not None and art.text else ""
            grp = dep.find("groupId")
            grp_text = grp.text.strip() if grp is not None and grp.text else ""
            full_dep = f"{grp_text}:{art_text}"

            for pattern, name in DEPENDENCY_MAPPINGS:
                if re.search(pattern, full_dep, re.IGNORECASE):
                    detected_deps.add(name)

        return BuildFacts(
            build_system="MAVEN",
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            java_version=java_version,
            spring_boot_version=spring_boot_version,
            detected_dependencies=list(detected_deps),
            evidence=evidence,
        )

    def _extract_gradle(self, file_path: str, content: str) -> BuildFacts:
        lines = content.splitlines()
        evidence = SourceEvidence(file=file_path, line_start=1, line_end=len(lines))

        group_id = None
        grp_match = re.search(r"""(?:group\s*=\s*['"]([^'"]+)['"]|group\s*\(\s*['"]([^'"]+)['"]\))""", content)
        if grp_match:
            group_id = grp_match.group(1) or grp_match.group(2)

        version = None
        ver_match = re.search(r"""(?:version\s*=\s*['"]([^'"]+)['"]|version\s*\(\s*['"]([^'"]+)['"]\))""", content)
        if ver_match:
            version = ver_match.group(1) or ver_match.group(2)

        java_version = None
        java_match = re.search(
            r"""(?:sourceCompatibility\s*=\s*['"]?(\d+|JavaVersion\.VERSION_(\d+))['"]?|jvmToolchain\s*\(\s*(\d+)\s*\)|languageVersion\.set\(JavaLanguageVersion\.of\((\d+)\)\))""",
            content,
        )
        if java_match:
            java_version = java_match.group(1) or java_match.group(2) or java_match.group(3) or java_match.group(4)
            if java_version and java_version.startswith("JavaVersion.VERSION_"):
                java_version = java_version.replace("JavaVersion.VERSION_", "").replace("_", ".")

        spring_boot_version = None
        boot_match = re.search(
            r"""id\s*\(?\s*['"]org\.springframework\.boot['"]\s*\)?\s*version\s*['"]([^'"]+)['"]""",
            content,
        )
        if boot_match:
            spring_boot_version = boot_match.group(1)

        detected_deps = set()
        for pattern, name in DEPENDENCY_MAPPINGS:
            if re.search(pattern, content, re.IGNORECASE):
                detected_deps.add(name)

        return BuildFacts(
            build_system="GRADLE",
            group_id=group_id,
            artifact_id=None,
            version=version,
            java_version=java_version,
            spring_boot_version=spring_boot_version,
            detected_dependencies=list(detected_deps),
            evidence=evidence,
        )
