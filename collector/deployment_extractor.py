"""Deployment, Helm, Kubernetes, and Dockerfile fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml
from publisher.repository_tools import RepositoryTools

from .models import DeploymentFacts, SourceEvidence

LOGGER = logging.getLogger(__name__)


class DeploymentExtractor:
    """Extracts deployment configuration, ports, replicas, resources, and probes from Helm, K8s, or Dockerfile."""

    def __init__(self, tools: RepositoryTools) -> None:
        self.tools = tools

    def extract(self) -> DeploymentFacts:
        try:
            files = self.tools.list_files(max_results=1000)
        except Exception:
            files = []

        # Priority 1: Helm values.yaml
        helm_files = [f for f in files if f.endswith("values.yaml") or f.endswith("values.yml")]
        if helm_files:
            for hf in helm_files:
                try:
                    content = self.tools.read_file(hf)
                    return self._parse_helm_values(hf, content)
                except Exception as exc:
                    LOGGER.warning("Could not parse Helm file %s: %s", hf, exc)

        # Priority 2: Kubernetes deployment.yaml
        k8s_files = [f for f in files if "deployment" in f.lower() and f.endswith((".yaml", ".yml"))]
        if k8s_files:
            for kf in k8s_files:
                try:
                    content = self.tools.read_file(kf)
                    return self._parse_k8s_deployment(kf, content)
                except Exception as exc:
                    LOGGER.warning("Could not parse K8s file %s: %s", kf, exc)

        # Priority 3: Dockerfile
        docker_files = [f for f in files if f.endswith("Dockerfile") or "dockerfile" in f.lower()]
        if docker_files:
            for df in docker_files:
                try:
                    content = self.tools.read_file(df)
                    return self._parse_dockerfile(df, content)
                except Exception as exc:
                    LOGGER.warning("Could not parse Dockerfile %s: %s", df, exc)

        return DeploymentFacts(descriptor_type="UNKNOWN")

    def _parse_helm_values(self, file_path: str, content: str) -> DeploymentFacts:
        lines = content.splitlines()
        evidence = SourceEvidence(file=file_path, line_start=1, line_end=len(lines))

        doc = yaml.safe_load(content)
        if not isinstance(doc, dict):
            return DeploymentFacts(descriptor_type="HELM", evidence=evidence)

        replica_count = doc.get("replicaCount") or doc.get("replicas")
        deployment_name = doc.get("nameOverride") or doc.get("fullnameOverride")

        # Service port
        service_port = None
        svc = doc.get("service")
        if isinstance(svc, dict):
            service_port = svc.get("port")

        # Container port
        container_port = None
        if isinstance(svc, dict) and svc.get("targetPort"):
            container_port = svc.get("targetPort")
        if not container_port and doc.get("containerPort"):
            container_port = doc.get("containerPort")

        # Resources
        cpu_req = None
        cpu_lim = None
        mem_req = None
        mem_lim = None
        res = doc.get("resources")
        if isinstance(res, dict):
            requests = res.get("requests")
            if isinstance(requests, dict):
                cpu_req = str(requests.get("cpu")) if requests.get("cpu") else None
                mem_req = str(requests.get("memory")) if requests.get("memory") else None
            limits = res.get("limits")
            if isinstance(limits, dict):
                cpu_lim = str(limits.get("cpu")) if limits.get("cpu") else None
                mem_lim = str(limits.get("memory")) if limits.get("memory") else None

        # Probes
        liveness_path = None
        readiness_path = None
        liveness = doc.get("livenessProbe")
        if isinstance(liveness, dict) and isinstance(liveness.get("httpGet"), dict):
            liveness_path = liveness["httpGet"].get("path")
        readiness = doc.get("readinessProbe")
        if isinstance(readiness, dict) and isinstance(readiness.get("httpGet"), dict):
            readiness_path = readiness["httpGet"].get("path")

        probe_path = readiness_path or liveness_path

        return DeploymentFacts(
            deployment_name=str(deployment_name) if deployment_name else None,
            container_port=container_port or service_port,
            service_port=service_port,
            replica_count=replica_count,
            cpu_request=cpu_req,
            cpu_limit=cpu_lim,
            memory_request=mem_req,
            memory_limit=mem_lim,
            health_probe_path=probe_path,
            readiness_probe_path=readiness_path,
            liveness_probe_path=liveness_path,
            descriptor_type="HELM",
            evidence=evidence,
        )

    def _parse_k8s_deployment(self, file_path: str, content: str) -> DeploymentFacts:
        lines = content.splitlines()
        evidence = SourceEvidence(file=file_path, line_start=1, line_end=len(lines))

        doc = yaml.safe_load(content)
        if not isinstance(doc, dict):
            return DeploymentFacts(descriptor_type="KUBERNETES", evidence=evidence)

        metadata = doc.get("metadata") or {}
        deployment_name = metadata.get("name") if isinstance(metadata, dict) else None

        spec = doc.get("spec") or {}
        replica_count = spec.get("replicas") if isinstance(spec, dict) else None

        container_port = None
        cpu_req = None
        cpu_lim = None
        mem_req = None
        mem_lim = None
        liveness_path = None
        readiness_path = None

        if isinstance(spec, dict):
            template = spec.get("template") or {}
            t_spec = template.get("spec") or {} if isinstance(template, dict) else {}
            containers = t_spec.get("containers") or [] if isinstance(t_spec, dict) else []
            if containers and isinstance(containers[0], dict):
                c0 = containers[0]
                ports = c0.get("ports") or []
                if ports and isinstance(ports[0], dict):
                    container_port = ports[0].get("containerPort")

                res = c0.get("resources") or {}
                if isinstance(res, dict):
                    reqs = res.get("requests") or {}
                    if isinstance(reqs, dict):
                        cpu_req = str(reqs.get("cpu")) if reqs.get("cpu") else None
                        mem_req = str(reqs.get("memory")) if reqs.get("memory") else None
                    lims = res.get("limits") or {}
                    if isinstance(lims, dict):
                        cpu_lim = str(lims.get("cpu")) if lims.get("cpu") else None
                        mem_lim = str(lims.get("memory")) if lims.get("memory") else None

                lp = c0.get("livenessProbe") or {}
                if isinstance(lp, dict) and isinstance(lp.get("httpGet"), dict):
                    liveness_path = lp["httpGet"].get("path")
                rp = c0.get("readinessProbe") or {}
                if isinstance(rp, dict) and isinstance(rp.get("httpGet"), dict):
                    readiness_path = rp["httpGet"].get("path")

        probe_path = readiness_path or liveness_path

        return DeploymentFacts(
            deployment_name=str(deployment_name) if deployment_name else None,
            container_port=container_port,
            service_port=container_port,
            replica_count=replica_count,
            cpu_request=cpu_req,
            cpu_limit=cpu_lim,
            memory_request=mem_req,
            memory_limit=mem_lim,
            health_probe_path=probe_path,
            readiness_probe_path=readiness_path,
            liveness_probe_path=liveness_path,
            descriptor_type="KUBERNETES",
            evidence=evidence,
        )

    def _parse_dockerfile(self, file_path: str, content: str) -> DeploymentFacts:
        lines = content.splitlines()
        evidence = SourceEvidence(file=file_path, line_start=1, line_end=len(lines))

        container_port = None
        expose_match = re.search(r"^\s*EXPOSE\s+(\d+)", content, re.MULTILINE | re.IGNORECASE)
        if expose_match:
            container_port = int(expose_match.group(1))

        return DeploymentFacts(
            container_port=container_port,
            descriptor_type="DOCKERFILE",
            evidence=evidence,
        )
