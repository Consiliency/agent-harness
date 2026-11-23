"""The LaneExec ``launch`` settings object: one strict, closed decoder (LANEEXEC binding §7 E3-2).

``ClientConfig`` is the captured :class:`~phase_loop_runtime.sandbox_policy.PlacementClientConfig`.
LaneExec reads its operator settings only from that configuration's top-level ``launch``
object, which ``config_sha256`` already covers (``x-launch-inputs.config_binding``). The wire
artifact does not freeze the object's shape; this module defines it, and every other LaneExec
module reads settings only through :func:`decode_launch_settings`.

The object, with every member optional::

    {
      "templates":                [<str>, ...],        # the template registry: each item is the
                                                       # registered file's bytes as UTF-8 text
      "toolkit_pins":             <str>,               # agent-toolkit only: the toolkit_pins.v1
                                                       # manifest bytes as UTF-8 text
      "images":                   [{"image_digest", "workload", "target_kind", "runtime"}, ...],
      "snapshot_limits":          {<limit>: int, ..., "by_workload": {...}, "by_target_kind": {...}},
      "seed_limits":              {<limit>: int, ..., "by_workload": {...}, "by_target_kind": {...}},
      "seed_root":                <absolute path> | null,     # agent-toolkit only
      "local_link_root":          <absolute path> | null,     # agent-toolkit only
      "local_pi_runner_launcher": "toolkit_interim" | "laneexec",  # agent-toolkit only
      "lane_placement":           "disabled" | "enabled",
      "routes_enabled":           [<route key>, ...],  # remote routes only, see REMOTE_ROUTES
      "return_max_bytes":         int,
      "snapshot_budget_s":        int,
      "return_budget_s":          int,
      "review_runner_image":      null | {...}         # the pinned image record (binding §6 E2-6)
    }

An absent ``launch`` object, or an absent member, means the shipped default. An unknown
member, a wrong type, or a value outside its frozen bound makes the configuration invalid,
raised as :class:`~phase_loop_runtime.sandbox_policy.PlacementConfigError` exactly as PLACECLI
treats an invalid client configuration. Operators may only lower the frozen limits and
budgets. No input value reaches an exception message.

Template records and the toolkit manifest are carried as text, not as parsed JSON, because
their identities are digests over exact bytes (``x-argv-templates.template_hash_rule``,
``x-contract-pins.toolkit_pins.manifest_check``); :mod:`phase_loop_runtime.launch_routes`
checks those bytes at registration.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping

from .sandbox_policy import PlacementClientConfig, PlacementConfigError

__all__ = [
    "DEFAULT_LAUNCH_SETTINGS",
    "DEFAULT_RETURN_BUDGET_S",
    "DEFAULT_RETURN_MAX_BYTES",
    "DEFAULT_SEED_LIMITS",
    "DEFAULT_SNAPSHOT_BUDGET_S",
    "DEFAULT_SNAPSHOT_LIMITS",
    "LANE_PLACEMENT_VALUES",
    "LOCAL_PI_RUNNER_LAUNCHERS",
    "REMOTE_ROUTES",
    "ImageEntry",
    "LaunchSettings",
    "ReviewRunnerImage",
    "decode_launch_object",
    "decode_launch_settings",
]

#: ``x-snapshot.limits`` defaults, which are also the ceilings.
DEFAULT_SNAPSHOT_LIMITS: Mapping[str, int] = MappingProxyType({
    "max_bytes": 536870912, "max_entries": 200000, "untracked_blob_max_bytes": 67108864,
})
#: ``x-seed.limits`` defaults (``$defs.SeedLimits`` holds them as ceilings).
DEFAULT_SEED_LIMITS: Mapping[str, int] = MappingProxyType({
    "max_entries": 4096, "entry_max_bytes": 16777216, "max_bytes": 67108864,
    "manifest_max_bytes": 1048576,
})
#: ``x-return.patch``: the default proposal cap, which operators may only lower.
DEFAULT_RETURN_MAX_BYTES = 67108864
#: ``x-lifetime.budget`` defaults, which operators may only lower.
DEFAULT_SNAPSHOT_BUDGET_S = 300
DEFAULT_RETURN_BUDGET_S = 120

#: ``x-activation.local_pi_runner_launcher``; the first is the shipped default.
LOCAL_PI_RUNNER_LAUNCHERS: tuple[str, ...] = ("toolkit_interim", "laneexec")
#: ``x-activation.lane_placement``; the first is the shipped default.
LANE_PLACEMENT_VALUES: tuple[str, ...] = ("disabled", "enabled")
#: Route enablement keys (``<workload>/<target_kind>``): the L-S7 rows whose shipped behavior
#: is ``sandbox_launch_route_disabled`` and that an operator value may enable. The local rows
#: are governed by ``lane_placement`` and ``local_pi_runner_launcher``; local ``leg`` and
#: ``qualification`` are always disabled and have no key.
REMOTE_ROUTES: tuple[str, ...] = ("pi-runner/openshell", "leg/openshell", "qualification/openshell")

_CLIENTS = ("agent-harness", "agent-toolkit")
_WORKLOADS = ("leg", "qualification", "implementation", "pi-runner")
_TARGET_KINDS = ("local", "openshell", "e2b")
_MEMBERS = frozenset({
    "templates", "toolkit_pins", "images", "snapshot_limits", "seed_limits", "seed_root",
    "local_link_root", "local_pi_runner_launcher", "lane_placement", "routes_enabled",
    "return_max_bytes", "snapshot_budget_s", "return_budget_s", "review_runner_image",
})
_TOOLKIT_ONLY = frozenset({"toolkit_pins", "seed_root", "local_link_root", "local_pi_runner_launcher"})
_MAX_TEMPLATES = 64
_MAX_IMAGES = 64
_MAX_TEXT_BYTES = 1048576
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_ABSOLUTE = re.compile(r"/[^\x00\r\n]{1,4095}")
_IMAGE_REF = re.compile(r"[a-z0-9.-]+(?::[0-9]{1,5})?(?:/[a-z0-9][a-z0-9._-]{0,63}){1,3}@sha256:[0-9a-f]{64}")
_HELPER_PATH = "/usr/libexec/agent-toolkit/landlock-exec"


def _invalid() -> PlacementConfigError:
    return PlacementConfigError()


def _require(condition: bool) -> None:
    if not condition:
        raise _invalid()


def _is_int(value: object) -> bool:
    return type(value) is int


def _closed(value: object, required: frozenset[str], optional: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    _require(isinstance(value, dict))
    keys = frozenset(value)  # type: ignore[arg-type]
    _require(required <= keys <= required | optional)
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class ImageEntry:
    """One image allowlist row for ``(client, workload, target_kind)``.

    ``runtime`` is the registered image's runtime record, which openshell registration reads
    (``x-argv-templates.pi_runner_templates.rule``); it is ``None`` on a local target, where
    ``image_digest`` names the registration and binds no container.
    """

    image_digest: str
    workload: str
    target_kind: str
    runtime: Mapping[str, Any] | None


@dataclass(frozen=True)
class ReviewRunnerImage:
    """The pinned review-runner image record (binding §6 E2-6), read here, consumed by SL-9."""

    image: str
    platform: str
    config_digest: str
    source_commit: str
    containerfile_sha256: str
    helper_path: str
    helper_sha256: str


@dataclass(frozen=True)
class LaunchSettings:
    """One client's decoded ``launch`` settings; every value is the effective one."""

    client: str
    templates: tuple[str, ...]
    toolkit_pins: str | None
    images: tuple[ImageEntry, ...]
    snapshot_limits: Mapping[str, Any]
    seed_limits: Mapping[str, Any]
    seed_root: str | None
    local_link_root: str | None
    local_pi_runner_launcher: str
    lane_placement: str
    routes_enabled: frozenset[str]
    return_max_bytes: int
    snapshot_budget_s: int
    return_budget_s: int
    review_runner_image: ReviewRunnerImage | None

    def effective_snapshot_limits(self, workload: str, target_kind: str) -> dict[str, int]:
        """``x-snapshot.limits``: the lowest of the default, the base and both selectors."""
        return _effective(DEFAULT_SNAPSHOT_LIMITS, self.snapshot_limits, workload, target_kind)

    def effective_seed_limits(self, workload: str, target_kind: str) -> dict[str, int]:
        """``x-seed.limits``: the lowest of the default, the base and both selectors."""
        return _effective(DEFAULT_SEED_LIMITS, self.seed_limits, workload, target_kind)

    def image_allowed(self, workload: str, target_kind: str, image_digest: str) -> bool:
        """``x-launch-inputs.binding``: the operator image allowlist for this client."""
        return self.image(workload, target_kind, image_digest) is not None

    def image(self, workload: str, target_kind: str, image_digest: str) -> ImageEntry | None:
        return next((entry for entry in self.images
                     if (entry.workload, entry.target_kind, entry.image_digest)
                     == (workload, target_kind, image_digest)), None)

    def route_enabled(self, workload: str, target_kind: str) -> bool:
        return f"{workload}/{target_kind}" in self.routes_enabled


def _effective(defaults: Mapping[str, int], configured: Mapping[str, Any], workload: str,
               target_kind: str) -> dict[str, int]:
    values = dict(defaults)
    layers = [configured, configured.get("by_workload", {}).get(workload, {}),
              configured.get("by_target_kind", {}).get(target_kind, {})]
    for layer in layers:
        for name in defaults:
            if name in layer:
                values[name] = min(values[name], layer[name])
    return values


def _limit_values(value: object, defaults: Mapping[str, int]) -> dict[str, int]:
    _require(isinstance(value, dict))
    out: dict[str, int] = {}
    for name, item in value.items():  # type: ignore[union-attr]
        _require(name in defaults and _is_int(item) and 0 <= item <= defaults[name])
        out[name] = item
    return out


def _limits(value: object, defaults: Mapping[str, int]) -> Mapping[str, Any]:
    _require(isinstance(value, dict))
    selectors = {"by_workload": _WORKLOADS, "by_target_kind": _TARGET_KINDS}
    base = {k: v for k, v in value.items() if k not in selectors}  # type: ignore[union-attr]
    out: dict[str, Any] = _limit_values(base, defaults)
    for selector, names in selectors.items():
        if selector not in value:  # type: ignore[operator]
            continue
        table = value[selector]  # type: ignore[index]
        _require(isinstance(table, dict))
        out[selector] = MappingProxyType({
            key: MappingProxyType(_limit_values(item, defaults))
            for key, item in table.items() if _require_key(key in names)
        })
    return MappingProxyType(out)


def _require_key(condition: bool) -> bool:
    _require(condition)
    return True


def _text(value: object) -> str:
    _require(isinstance(value, str) and 0 < len(value))
    try:
        size = len(value.encode("utf-8"))  # type: ignore[union-attr]
    except UnicodeEncodeError:
        raise _invalid() from None
    _require(size <= _MAX_TEXT_BYTES)
    return value  # type: ignore[return-value]


def _absolute_or_null(value: object) -> str | None:
    if value is None:
        return None
    _require(isinstance(value, str) and _ABSOLUTE.fullmatch(value) is not None)
    parts = value.split("/")[1:]  # type: ignore[union-attr]
    _require(all(part not in ("", ".", "..") for part in parts))
    return value  # type: ignore[return-value]


def _runtime(value: object) -> Mapping[str, Any]:
    """The runtime record of an openshell image, checked for shape only.

    ``{"version": 3, "helper": {"path", "version", "sha256"}, "node": {"path", "sha256"},
    "launcher": {"path", "files": {<manifest path>: <hex sha256>}}, "trees": [<image path>]}``
    """
    record = _closed(value, frozenset({"version", "helper", "node", "launcher", "trees"}))
    _require(record["version"] == 3 and _is_int(record["version"]))
    helper = _closed(record["helper"], frozenset({"path", "version", "sha256"}))
    _require(helper["path"] == _HELPER_PATH and helper["version"] == 1 and _is_int(helper["version"]))
    _require(isinstance(helper["sha256"], str) and _HEX64.fullmatch(helper["sha256"]) is not None)
    node = _closed(record["node"], frozenset({"path", "sha256"}))
    _require(_absolute_or_null(node["path"]) is not None)
    _require(isinstance(node["sha256"], str) and _HEX64.fullmatch(node["sha256"]) is not None)
    launcher = _closed(record["launcher"], frozenset({"path", "files"}))
    _require(_absolute_or_null(launcher["path"]) is not None)
    files = launcher["files"]
    _require(isinstance(files, dict) and 0 < len(files) <= 512)
    for path, digest in files.items():
        _require(isinstance(path, str) and 0 < len(path) <= 1024 and not path.startswith("/"))
        _require(all(part not in ("", ".", "..") for part in path.split("/")))
        _require(isinstance(digest, str) and _HEX64.fullmatch(digest) is not None)
    trees = record["trees"]
    _require(isinstance(trees, list) and len(trees) <= 64)
    for tree in trees:
        _require(_absolute_or_null(tree) is not None)
    _require(len(set(trees)) == len(trees))
    return MappingProxyType({
        "version": 3,
        "helper": MappingProxyType(dict(helper)),
        "node": MappingProxyType(dict(node)),
        "launcher": MappingProxyType({"path": launcher["path"], "files": MappingProxyType(dict(files))}),
        "trees": tuple(trees),
    })


def _images(value: object) -> tuple[ImageEntry, ...]:
    _require(isinstance(value, list) and len(value) <= _MAX_IMAGES)
    out: list[ImageEntry] = []
    for item in value:  # type: ignore[union-attr]
        row = _closed(item, frozenset({"image_digest", "workload", "target_kind", "runtime"}))
        _require(isinstance(row["image_digest"], str)
                 and _SHA256_DIGEST.fullmatch(row["image_digest"]) is not None)
        _require(row["workload"] in _WORKLOADS and row["target_kind"] in _TARGET_KINDS)
        if row["target_kind"] == "openshell":
            runtime = None if row["runtime"] is None else _runtime(row["runtime"])
        else:
            _require(row["runtime"] is None)
            runtime = None
        out.append(ImageEntry(row["image_digest"], row["workload"], row["target_kind"], runtime))
    keys = [(e.image_digest, e.workload, e.target_kind) for e in out]
    _require(len(set(keys)) == len(keys))
    return tuple(out)


def _review_runner_image(value: object) -> ReviewRunnerImage | None:
    if value is None:
        return None
    record = _closed(value, frozenset({"image", "platform", "config_digest", "source_commit",
                                       "containerfile_sha256", "helper"}))
    helper = _closed(record["helper"], frozenset({"path", "sha256"}))
    _require(isinstance(record["image"], str) and _IMAGE_REF.fullmatch(record["image"]) is not None)
    _require(record["platform"] == "linux/amd64")
    _require(isinstance(record["config_digest"], str)
             and _SHA256_DIGEST.fullmatch(record["config_digest"]) is not None)
    _require(isinstance(record["source_commit"], str)
             and _HEX40.fullmatch(record["source_commit"]) is not None)
    for digest in (record["containerfile_sha256"], helper["sha256"]):
        _require(isinstance(digest, str) and _HEX64.fullmatch(digest) is not None)
    _require(helper["path"] == _HELPER_PATH)
    return ReviewRunnerImage(record["image"], record["platform"], record["config_digest"],
                             record["source_commit"], record["containerfile_sha256"],
                             helper["path"], helper["sha256"])


def _bounded_int(value: object, low: int, high: int) -> int:
    _require(_is_int(value) and low <= value <= high)  # type: ignore[operator]
    return value  # type: ignore[return-value]


def decode_launch_object(launch: Mapping[str, Any] | None, *, client: str) -> LaunchSettings:
    """Decode one client's ``launch`` object; ``None`` is the shipped defaults."""
    _require(client in _CLIENTS)
    value: Mapping[str, Any] = {} if launch is None else launch
    _require(isinstance(value, Mapping))
    _require(frozenset(value) <= _MEMBERS)
    if client != "agent-toolkit":
        _require(not (frozenset(value) & _TOOLKIT_ONLY))

    templates_raw = value.get("templates", [])
    _require(isinstance(templates_raw, list) and len(templates_raw) <= _MAX_TEMPLATES)
    templates = tuple(_text(item) for item in templates_raw)
    toolkit_pins = None if "toolkit_pins" not in value else _text(value["toolkit_pins"])

    routes_raw = value.get("routes_enabled", [])
    _require(isinstance(routes_raw, list) and all(item in REMOTE_ROUTES for item in routes_raw))
    _require(len(set(routes_raw)) == len(routes_raw))

    launcher = value.get("local_pi_runner_launcher", LOCAL_PI_RUNNER_LAUNCHERS[0])
    _require(launcher in LOCAL_PI_RUNNER_LAUNCHERS)
    lane_placement = value.get("lane_placement", LANE_PLACEMENT_VALUES[0])
    _require(lane_placement in LANE_PLACEMENT_VALUES)

    return LaunchSettings(
        client=client,
        templates=templates,
        toolkit_pins=toolkit_pins,
        images=_images(value.get("images", [])),
        snapshot_limits=_limits(value.get("snapshot_limits", {}), DEFAULT_SNAPSHOT_LIMITS),
        seed_limits=_limits(value.get("seed_limits", {}), DEFAULT_SEED_LIMITS),
        seed_root=_absolute_or_null(value.get("seed_root")),
        local_link_root=_absolute_or_null(value.get("local_link_root")),
        local_pi_runner_launcher=launcher,
        lane_placement=lane_placement,
        routes_enabled=frozenset(routes_raw),
        return_max_bytes=_bounded_int(value.get("return_max_bytes", DEFAULT_RETURN_MAX_BYTES),
                                      0, DEFAULT_RETURN_MAX_BYTES),
        snapshot_budget_s=_bounded_int(value.get("snapshot_budget_s", DEFAULT_SNAPSHOT_BUDGET_S),
                                       1, DEFAULT_SNAPSHOT_BUDGET_S),
        return_budget_s=_bounded_int(value.get("return_budget_s", DEFAULT_RETURN_BUDGET_S),
                                     1, DEFAULT_RETURN_BUDGET_S),
        review_runner_image=_review_runner_image(value.get("review_runner_image")),
    )


def decode_launch_settings(config: PlacementClientConfig) -> LaunchSettings:
    """The settings of one captured client configuration (``x-launch-inputs.config_binding``)."""
    return decode_launch_object(config.launch, client=config.client)


#: The shipped defaults, for each client.
DEFAULT_LAUNCH_SETTINGS: Mapping[str, LaunchSettings] = MappingProxyType({
    client: decode_launch_object(None, client=client) for client in _CLIENTS
})
