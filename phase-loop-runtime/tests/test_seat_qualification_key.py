from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from executable_dependency_test_support import build_fixture
from phase_loop_runtime import seat_qualification_key
from phase_loop_runtime.executable_dependency import ExecutableDependencyError
from phase_loop_runtime.seat_route_contract import QualificationKey, key_digest, record_binding


def _profile(*, leg: str = "claude", projection: str = "optional") -> SimpleNamespace:
    return SimpleNamespace(leg=leg, projection=projection)


def _projection(digest: str) -> SimpleNamespace:
    return SimpleNamespace(projection_digest=digest)


def _live_inputs(
    monkeypatch,
    *,
    profile_digest: str = "p",
    layout: str = "layout",
    host: str = "host",
):
    monkeypatch.setattr(
        seat_qualification_key.seat_jail,
        "jail_profile_digest",
        lambda _leg: profile_digest,
    )
    monkeypatch.setattr(
        seat_qualification_key.seat_jail,
        "falsifier_layout_identity",
        lambda: layout,
    )
    monkeypatch.setattr(seat_qualification_key.seat_jail, "host_identity", lambda: host)


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("profile_digest", "profile-b"),
        ("allowlist_digest", "allowlist-b"),
        ("falsifier_layout", "layout-b"),
        ("projection_digest", "projection-b"),
        ("variant", "sdk"),
        ("host_identity", "host-b"),
    ),
)
def test_each_live_key_part_changes_digest_and_record_binding(
    monkeypatch, field, changed
):
    values = {
        "profile_digest": "profile-a",
        "allowlist_digest": "allowlist-a",
        "falsifier_layout": "layout-a",
        "projection_digest": "projection-a",
        "variant": "tui",
        "host_identity": "host-a",
    }

    def build(parts):
        _live_inputs(
            monkeypatch,
            profile_digest=parts["profile_digest"],
            layout=parts["falsifier_layout"],
            host=parts["host_identity"],
        )
        return seat_qualification_key.key_for_launch(
            _profile(),
            variant=parts["variant"],
            allowlist_digest=parts["allowlist_digest"],
            projection=_projection(parts["projection_digest"]),
        )

    baseline = build(values)
    candidate = build({**values, field: changed})
    assert key_digest(candidate) != key_digest(baseline)
    assert dict(record_binding(candidate)) != dict(record_binding(baseline))


def test_live_inputs_land_in_their_own_key_fields(monkeypatch):
    jail = seat_qualification_key.seat_jail
    monkeypatch.setattr(jail, "host_identity", lambda: "h" * 64)
    key = seat_qualification_key.key_for_launch(
        _profile(leg="gemini", projection="optional"),
        variant="variant-sentinel",
        allowlist_digest="a" * 64,
        projection=_projection("d" * 64),
    )
    assert key == QualificationKey(
        profile_digest=jail.jail_profile_digest("gemini"),
        allowlist_digest="a" * 64,
        falsifier_layout=jail.falsifier_layout_identity(),
        projection_digest="d" * 64,
        variant="variant-sentinel",
        host_identity="h" * 64,
    )
    assert key.profile_digest != jail.jail_profile_digest("claude")


def _allowlist_digest(monkeypatch, tmp_path, refused_extra: tuple[str, ...]) -> str:
    """The real SL-1 content digest of the packaged Gemini allowlist, widened by
    ``refused_extra`` measured-and-refused hosts."""
    from phase_loop_runtime import seat_egress_proxy

    real_data_path = seat_egress_proxy._data_path
    document = json.loads(real_data_path("gemini-allowlist.json").read_text(encoding="utf-8"))
    document["measured_and_refused"] = [*document["measured_and_refused"], *refused_extra]
    fixture = tmp_path / f"gemini-allowlist-{len(refused_extra)}.json"
    fixture.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        seat_egress_proxy, "_data_path",
        lambda name: fixture if name == "gemini-allowlist.json" else real_data_path(name),
    )
    try:
        return seat_egress_proxy.allowlist_ref("gemini").content_digest
    finally:
        monkeypatch.setattr(seat_egress_proxy, "_data_path", real_data_path)


def test_widened_refusal_layout_and_switched_transport_invalidate_old_pass(
    monkeypatch, tmp_path
):
    _live_inputs(monkeypatch)
    old = seat_qualification_key.key_for_launch(
        _profile(),
        variant="tui",
        allowlist_digest=_allowlist_digest(monkeypatch, tmp_path, ()),
        projection=None,
    )
    widened = seat_qualification_key.key_for_launch(
        _profile(),
        variant="tui",
        allowlist_digest=_allowlist_digest(monkeypatch, tmp_path, ("also-refused.invalid",)),
        projection=None,
    )
    switched = seat_qualification_key.key_for_launch(
        _profile(),
        variant="sdk",
        allowlist_digest=old.allowlist_digest,
        projection=None,
    )
    old_pass = {"qualification_key": dict(record_binding(old))}
    assert old_pass["qualification_key"] != dict(record_binding(widened))
    assert old_pass["qualification_key"] != dict(record_binding(switched))
    assert key_digest(old) not in {key_digest(widened), key_digest(switched)}


def test_projection_mode_refusals_precede_admission():
    requirement = SimpleNamespace(provider="synthetic")
    with pytest.raises(ExecutableDependencyError, match="authority_invalid"):
        seat_qualification_key.admit_profile_projection(
            _profile(leg="synthetic", projection="none"),
            requirement,
        )
    with pytest.raises(ExecutableDependencyError, match="authority_missing"):
        seat_qualification_key.admit_profile_projection(
            _profile(leg="synthetic", projection="required"),
            None,
        )
    assert (
        seat_qualification_key.admit_profile_projection(
            _profile(leg="synthetic", projection="optional"),
            None,
        )
        is None
    )


def test_optional_non_claude_profile_uses_real_generic_admission(tmp_path):
    fixture = build_fixture(tmp_path / "synthetic", provider="synthetic")
    carrier = SimpleNamespace(
        requirement=fixture.requirement,
        borrowed_authority_fd=fixture.authority_fd,
        expected_authority_sha256=fixture.requirement.expected_authority_sha256,
    )
    try:
        admitted = seat_qualification_key.admit_profile_projection(
            _profile(leg="synthetic", projection="optional"),
            carrier,
        )
        assert admitted is not None
        try:
            assert admitted.provider == "synthetic"
            assert admitted.projection_digest
            admitted.revalidate()
            assert (
                seat_qualification_key.admit_profile_projection(
                    _profile(leg="synthetic", projection="optional"), admitted
                )
                is admitted
            )
        finally:
            admitted.close()
        fixture.authority_path.stat()
    finally:
        fixture.close()


def test_requirement_provider_must_match_profile(tmp_path):
    fixture = build_fixture(tmp_path / "mismatch", provider="synthetic")
    carrier = SimpleNamespace(
        requirement=fixture.requirement,
        borrowed_authority_fd=fixture.authority_fd,
        expected_authority_sha256=fixture.requirement.expected_authority_sha256,
    )
    try:
        with pytest.raises(
            ExecutableDependencyError, match="profile provider mismatch"
        ):
            seat_qualification_key.admit_profile_projection(
                _profile(leg="other", projection="required"),
                carrier,
            )
    finally:
        fixture.close()


def test_projection_object_and_host_identity_are_closed(monkeypatch):
    _live_inputs(monkeypatch, host="")
    with pytest.raises(ValueError, match="host identity"):
        seat_qualification_key.key_for_launch(
            _profile(),
            variant=None,
            allowlist_digest=None,
            projection=None,
        )

    _live_inputs(monkeypatch)
    with pytest.raises(ValueError, match="projection.*digest"):
        seat_qualification_key.key_for_launch(
            _profile(),
            variant=None,
            allowlist_digest=None,
            projection=object(),
        )
