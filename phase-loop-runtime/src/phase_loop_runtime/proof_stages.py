"""Independent local proof stages and content-bound caching."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .producer_manifest import ProducerManifest


@dataclass(frozen=True)
class StageOutcome:
    ok: bool
    value: Any = None
    error: Exception | None = None


class LocalStageCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._values: dict[str, Any] = {}

    def get_or_run(
        self,
        stage: str,
        input_digests: tuple[str, ...],
        producer: ProducerManifest,
        runner: Callable[[], Any],
    ) -> Any:
        payload = {
            "stage": stage,
            "input_digests": sorted(input_digests),
            "producer": asdict(producer),
        }
        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        cache_path = self.root / f"{key}.json"
        if key not in self._values:
            self.root.mkdir(parents=True, exist_ok=True)
            if cache_path.is_file() and not cache_path.is_symlink():
                try:
                    self._values[key] = json.loads(cache_path.read_text(encoding="utf-8"))["value"]
                except (OSError, KeyError, json.JSONDecodeError, TypeError):
                    cache_path.unlink(missing_ok=True)
            if key not in self._values:
                value = runner()
                self._values[key] = value
                try:
                    rendered = json.dumps({"key": key, "value": value}, sort_keys=True) + "\n"
                except TypeError:
                    return value
                temporary = cache_path.with_suffix(".tmp")
                temporary.write_text(rendered, encoding="utf-8")
                temporary.replace(cache_path)
        return self._values[key]


def run_independent_stages(
    stages: Mapping[str, Callable[[], Any]], *, max_workers: int
) -> dict[str, StageOutcome]:
    outcomes: dict[str, StageOutcome] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(stage): name for name, stage in stages.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                outcomes[name] = StageOutcome(ok=True, value=future.result())
            except Exception as exc:
                outcomes[name] = StageOutcome(ok=False, error=exc)
    return outcomes
