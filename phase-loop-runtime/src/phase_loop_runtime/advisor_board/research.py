"""Version-pinned, privacy-safe PMCP research for advisor-board seats."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .schema import ResearchPolicy

MCP_SERVER_NAME = "pmcp_advisor"
RESEARCH_CAPABLE_LANES = frozenset({"claude", "codex"})
_ACTIVATION_REQUIREMENTS = frozenset(
    {
        "explicit_policy",
        "gateway_tool_filtering",
        "typed_correlations",
        "explicit_audit_jsonl",
        "unique_lock_dir",
        "terminal_completion_fsync",
    }
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ResearchUnavailable(RuntimeError):
    """The scoped research profile cannot be proven before launch."""


class ResearchAuditError(RuntimeError):
    """A seat's audit is missing, incomplete, or does not match its contract."""


@dataclass(frozen=True)
class ResearchSeatConfig:
    lane: str
    run_correlation_id: str
    seat_correlation_id: str
    evidence_label: str
    evidence_label_digest: str
    policy_path: Path
    provider_config_path: Path
    manifest_path: Path
    policy_digest: str
    lock_dir: Path
    audit_path: Path
    pmcp_command: tuple[str, ...]

    @property
    def pmcp_args(self) -> tuple[str, ...]:
        return (
            *self.pmcp_command[1:],
            "--project",
            str(self.policy_path.parent),
            "--config",
            str(self.provider_config_path),
            "--policy",
            str(self.policy_path),
            "--lock-dir",
            str(self.lock_dir),
            "--audit-jsonl",
            str(self.audit_path),
            "--quiet",
        )

    @property
    def mcp_server(self) -> dict[str, Any]:
        return {
            "type": "stdio",
            "command": self.pmcp_command[0],
            "args": list(self.pmcp_args),
            "env": {"PMCP_MANIFEST_PATH": str(self.manifest_path)},
        }


@dataclass(frozen=True)
class ResearchRunConfig:
    root: Path
    run_correlation_id: str
    policy_digest: str
    seats: tuple[ResearchSeatConfig, ...]

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@dataclass(frozen=True)
class ResearchInvocation:
    downstream_tool_id: str | None
    terminal_status: str
    source_reference_hash: str | None
    evidence_label_digest: str | None
    claim_status: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "downstream_tool_id": self.downstream_tool_id,
            "terminal_status": self.terminal_status,
            "source_reference_hash": self.source_reference_hash,
            "evidence_label_digest": self.evidence_label_digest,
            "claim_status": self.claim_status,
        }


@dataclass(frozen=True)
class ResearchLedger:
    status: str
    policy_digest: str | None
    audit_digest: str | None
    ledger_digest: str
    invocations: tuple[ResearchInvocation, ...] = ()
    detail: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "policy_digest": self.policy_digest,
            "audit_digest": self.audit_digest,
            "ledger_digest": self.ledger_digest,
            "invocations": [entry.to_safe_dict() for entry in self.invocations],
            "detail": self.detail,
        }


def _digest_json(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _policy_payload(policy: ResearchPolicy) -> dict[str, Any]:
    return {
        "servers": {"allowlist": list(policy.servers), "denylist": []},
        "gateway_tools": {"allowlist": list(policy.gateway_tools), "denylist": []},
        "tools": {"allowlist": list(policy.tool_patterns), "denylist": []},
        "resources": {"allowlist": [], "denylist": ["*"]},
        "prompts": {"allowlist": [], "denylist": ["*"]},
        "limits": {
            "max_tools_per_server": 100,
            "max_output_bytes": 50000,
            "max_output_tokens": 4000,
        },
        "redaction": {"patterns": []},
    }


def scrub_research_env(env: Mapping[str, str] | None) -> dict[str, str]:
    """Remove ambient PMCP controls before a governed probe or seat launch."""
    result = dict(os.environ if env is None else env)
    return {key: value for key, value in result.items() if not key.startswith("PMCP_")}


def _provider_config_payload() -> dict[str, Any]:
    return {
        "mcpServers": {
            "firecrawl": {
                "command": "npx",
                "args": ["-y", "firecrawl-mcp"],
            },
            "brightdata": {
                "command": "npx",
                "args": ["-y", "@brightdata/mcp"],
            },
        }
    }


def _manifest_payload() -> dict[str, Any]:
    platforms = ("mac", "wsl", "linux", "windows")
    firecrawl_install = ["npx", "-y", "firecrawl-mcp"]
    brightdata_install = ["npx", "-y", "@brightdata/mcp"]
    return {
        "version": "1.0",
        "servers": {
            "firecrawl": {
                "description": "Firecrawl MCP",
                "keywords": ["firecrawl", "scraping", "crawling", "extract"],
                "install": {name: firecrawl_install for name in platforms},
                "command": "npx",
                "args": ["-y", "firecrawl-mcp"],
                "requires_api_key": True,
                "env_var": "FIRECRAWL_API_KEY",
            },
            "brightdata": {
                "description": "Bright Data MCP",
                "keywords": ["brightdata", "scraping", "web research"],
                "install": {name: brightdata_install for name in platforms},
                "command": "npx",
                "args": ["-y", "@brightdata/mcp"],
                "requires_api_key": True,
                "env_var": "API_TOKEN",
                "secret_key": "BRIGHTDATA_API_TOKEN",
            },
        },
    }


def probe_research_capability(
    policy: ResearchPolicy,
    *,
    env: Mapping[str, str] | None = None,
    run: Any = subprocess.run,
) -> dict[str, Any]:
    """Require the exact released PMCP capability before any seat is launched."""
    try:
        completed = run(
            [*policy.pmcp_command, "capabilities", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=scrub_research_env(env),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResearchUnavailable("pmcp_capability_probe_failed") from exc
    if completed.returncode != 0:
        raise ResearchUnavailable("pmcp_capability_probe_failed")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResearchUnavailable("pmcp_capability_probe_invalid") from exc
    if payload.get("pmcp_version") != policy.required_version:
        raise ResearchUnavailable("pmcp_version_mismatch")
    capability = next(
        (
            item
            for item in payload.get("capabilities", [])
            if isinstance(item, dict) and item.get("name") == policy.required_capability
        ),
        None,
    )
    if capability is None:
        raise ResearchUnavailable("pmcp_capability_missing")
    if frozenset(capability.get("activation_requires", [])) != _ACTIVATION_REQUIREMENTS:
        raise ResearchUnavailable("pmcp_capability_incomplete")
    return payload


def materialize_research_run(
    policy: ResearchPolicy,
    seats: Sequence[tuple[str, str]],
    *,
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
    probe_run: Any = subprocess.run,
) -> ResearchRunConfig:
    if not policy.enabled:
        raise ValueError("cannot materialize disabled research policy")
    probe_research_capability(policy, env=env, run=probe_run)
    run_root: Path | None = None
    created_by_us = False
    try:
        if root is None:
            run_root = Path(tempfile.mkdtemp(prefix="pl-board-research-"))
            created_by_us = True
        else:
            run_root = Path(root)
            run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
            created_by_us = True
        policy_payload = _policy_payload(policy)
        policy_bytes = json.dumps(
            policy_payload, separators=(",", ":"), ensure_ascii=True
        )
        policy_path = run_root / "policy.json"
        policy_path.write_text(policy_bytes + "\n", encoding="utf-8")
        policy_path.chmod(0o400)
        provider_config_path = run_root / ".mcp.json"
        provider_config_path.write_text(
            json.dumps(_provider_config_payload(), separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        provider_config_path.chmod(0o400)
        manifest_dir = run_root / ".pmcp"
        manifest_dir.mkdir(mode=0o700)
        manifest_path = manifest_dir / "manifest.yaml"
        manifest_path.write_text(
            json.dumps(_manifest_payload(), separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o400)
        policy_digest = hashlib.sha256(policy_bytes.encode("utf-8")).hexdigest()
        run_id = f"research-{uuid.uuid4().hex}"
        seat_configs: list[ResearchSeatConfig] = []
        for index, (lane, _seat_key) in enumerate(seats):
            seat_id = f"seat-{index:04d}"
            evidence_label = f"research-evidence-{index:04d}"
            seat_root = run_root / seat_id
            lock_dir = seat_root / "lock"
            lock_dir.mkdir(parents=True, mode=0o700)
            seat_configs.append(
                ResearchSeatConfig(
                    lane=lane,
                    run_correlation_id=run_id,
                    seat_correlation_id=seat_id,
                    evidence_label=evidence_label,
                    evidence_label_digest=hashlib.sha256(
                        evidence_label.encode("utf-8")
                    ).hexdigest(),
                    policy_path=policy_path,
                    provider_config_path=provider_config_path,
                    manifest_path=manifest_path,
                    policy_digest=policy_digest,
                    lock_dir=lock_dir,
                    audit_path=seat_root / "audit.jsonl",
                    pmcp_command=policy.pmcp_command,
                )
            )
        return ResearchRunConfig(
            root=run_root,
            run_correlation_id=run_id,
            policy_digest=policy_digest,
            seats=tuple(seat_configs),
        )
    except OSError as exc:
        if run_root is not None and created_by_us:
            shutil.rmtree(run_root, ignore_errors=True)
        raise ResearchUnavailable("research_materialization_failed") from exc


def research_instructions(config: ResearchSeatConfig) -> str:
    return (
        "\n\n## Governed advisor research\n"
        f"Use only the session-local MCP server `{MCP_SERVER_NAME}`. Discover with "
        "gateway.health, gateway.catalog_search, and gateway.describe. Invoke only "
        "approved Firecrawl or Bright Data research tools through gateway.invoke. "
        "Every gateway.invoke call must include these exact top-level fields: "
        f"run_correlation_id={config.run_correlation_id!r}, "
        f"seat_correlation_id={config.seat_correlation_id!r}, and "
        f"evidence_label_digest={config.evidence_label_digest!r}. "
        f"For any source-backed claim, include the label `{config.evidence_label}` "
        "in your final response. Do not claim a call succeeded unless its tool result "
        "reported success. Mutation and lifecycle controls are forbidden.\n"
    )


def mcp_tool_names() -> tuple[str, ...]:
    return (
        f"mcp__{MCP_SERVER_NAME}__gateway_health",
        f"mcp__{MCP_SERVER_NAME}__gateway_catalog_search",
        f"mcp__{MCP_SERVER_NAME}__gateway_describe",
        f"mcp__{MCP_SERVER_NAME}__gateway_invoke",
    )


def claude_mcp_config(config: ResearchSeatConfig) -> str:
    return json.dumps(
        {"mcpServers": {MCP_SERVER_NAME: config.mcp_server}}, separators=(",", ":")
    )


def codex_mcp_args(config: ResearchSeatConfig) -> tuple[str, ...]:
    prefix = f"mcp_servers.{MCP_SERVER_NAME}"
    return (
        "--ignore-user-config",
        "--strict-config",
        "-c",
        'web_search="disabled"',
        "-c",
        "features.apps=false",
        "-c",
        "features.remote_plugin=false",
        "-c",
        f"{prefix}.command={json.dumps(config.pmcp_command[0])}",
        "-c",
        f"{prefix}.args={json.dumps(list(config.pmcp_args), separators=(',', ':'))}",
        "-c",
        f"{prefix}.enabled=true",
        "-c",
        f"{prefix}.required=true",
        "-c",
        f'{prefix}.default_tools_approval_mode="approve"',
        "-c",
        f"{prefix}.enabled_tools={json.dumps(list(configured_gateway_tool_names()), separators=(',', ':'))}",
    )


def configured_gateway_tool_names() -> tuple[str, ...]:
    """Names as advertised by PMCP over MCP, without client-specific prefixes."""
    return ("gateway.health", "gateway.catalog_search", "gateway.describe", "gateway.invoke")


def unavailable_ledger(detail: str) -> ResearchLedger:
    payload = {"status": "unavailable", "detail": detail}
    return ResearchLedger(
        status="unavailable",
        policy_digest=None,
        audit_digest=None,
        ledger_digest=_digest_json(payload),
        detail=detail,
    )


def _validated_records(config: ResearchSeatConfig) -> tuple[list[dict[str, Any]], str]:
    try:
        raw = config.audit_path.read_bytes()
        records = [
            json.loads(line)
            for line in raw.decode("utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:
        raise ResearchAuditError("audit_unreadable") from exc
    if not records:
        raise ResearchAuditError("audit_empty")
    if not all(isinstance(record, dict) for record in records):
        raise ResearchAuditError("audit_record_invalid")
    if [record.get("sequence") for record in records] != list(
        range(1, len(records) + 1)
    ):
        raise ResearchAuditError("audit_sequence_gap")
    starts = [record for record in records if record.get("event") == "audit.started"]
    completions = [
        record for record in records if record.get("event") == "audit.completed"
    ]
    if len(starts) != 1 or records[0] is not starts[0]:
        raise ResearchAuditError("audit_start_invalid")
    if len(completions) != 1 or records[-1] is not completions[0]:
        raise ResearchAuditError("audit_completion_invalid")
    terminal = completions[0]
    if (
        terminal.get("first_sequence") != 1
        or terminal.get("last_sequence") != len(records)
        or terminal.get("record_count") != len(records)
    ):
        raise ResearchAuditError("audit_completion_bounds")
    policy_digests = {record.get("policy_digest") for record in records}
    session_ids = {record.get("audit_session_id") for record in records}
    if policy_digests != {config.policy_digest}:
        raise ResearchAuditError("audit_policy_mismatch")
    if len(session_ids) != 1 or None in session_ids:
        raise ResearchAuditError("audit_session_mismatch")
    return records, hashlib.sha256(raw).hexdigest()


def reduce_research_audit(config: ResearchSeatConfig, seat_text: str) -> ResearchLedger:
    try:
        records, audit_digest = _validated_records(config)
    except ResearchAuditError as exc:
        detail = str(exc)
        payload = {
            "status": "failed",
            "policy_digest": config.policy_digest,
            "detail": detail,
        }
        return ResearchLedger(
            status="failed",
            policy_digest=config.policy_digest,
            audit_digest=None,
            ledger_digest=_digest_json(payload),
            detail=detail,
        )

    invocations: list[ResearchInvocation] = []
    correlation_mismatch = False
    for record in records:
        if (
            record.get("event") != "audit.invocation"
            or record.get("gateway_tool") != "gateway.invoke"
        ):
            continue
        tool_id = record.get("downstream_tool_id")
        terminal_status = str(record.get("terminal_status") or "failure")
        source_hash = record.get("source_reference_hash")
        evidence_digest = record.get("evidence_label_digest")
        correlated = (
            record.get("run_correlation_id") == config.run_correlation_id
            and record.get("seat_correlation_id") == config.seat_correlation_id
            and evidence_digest == config.evidence_label_digest
        )
        correlation_mismatch = correlation_mismatch or not correlated
        verified = (
            correlated
            and terminal_status == "success"
            and isinstance(source_hash, str)
            and bool(_DIGEST_RE.fullmatch(source_hash))
            and config.evidence_label in seat_text
        )
        invocations.append(
            ResearchInvocation(
                downstream_tool_id=tool_id if isinstance(tool_id, str) else None,
                terminal_status=terminal_status,
                source_reference_hash=source_hash
                if isinstance(source_hash, str) and _DIGEST_RE.fullmatch(source_hash)
                else None,
                evidence_label_digest=evidence_digest
                if isinstance(evidence_digest, str)
                and _DIGEST_RE.fullmatch(evidence_digest)
                else None,
                claim_status="verified" if verified else "unverified",
            )
        )
    statuses = {entry.terminal_status for entry in invocations}
    detail = "audit_correlation_mismatch" if correlation_mismatch else None
    if correlation_mismatch:
        status = "failed"
    elif any(entry.claim_status == "verified" for entry in invocations):
        status = "success"
    elif "denied" in statuses:
        status = "denied"
    elif invocations:
        status = "failed"
    else:
        status = "no_calls"
    ledger_payload = {
        "status": status,
        "policy_digest": config.policy_digest,
        "audit_digest": audit_digest,
        "invocations": [entry.to_safe_dict() for entry in invocations],
        "detail": detail,
    }
    return ResearchLedger(
        status=status,
        policy_digest=config.policy_digest,
        audit_digest=audit_digest,
        ledger_digest=_digest_json(ledger_payload),
        invocations=tuple(invocations),
        detail=detail,
    )
