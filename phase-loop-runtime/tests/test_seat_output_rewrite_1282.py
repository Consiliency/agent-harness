"""A seat profile's exit rewrites a retained output only to remove a copied secret
(agent-harness#1282 Gate A, py3.11 flake). Rewriting every output unconditionally is a
read-truncate-write: a write that lands between the read and the truncate is lost. It was
observed when one declared output file was shared across concurrent profiles (an auth probe
and two seats): the probe's exit wiped both seats' lines."""

from __future__ import annotations

from phase_loop_runtime import panel_invoker as pi


def _profile_with_a_secret(tmp_path, output):
    home = tmp_path / "operator"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex/auth.json").write_text('{"tokens":{"access_token":"synthetic-access-token"}}')
    return pi._seat_command_profile(["/usr/bin/true"], env={"HOME": str(home)}, cwd=tmp_path,
                                    outputs=(output,), role=pi.SeatLaunchRole.PROVIDER_ADMIN)


def test_an_output_without_a_secret_is_not_rewritten(tmp_path, monkeypatch):
    output = tmp_path / "shared-output"
    real_read = pi.read_seat_output

    def read_then_a_concurrent_write(*args, **kwargs):
        data = real_read(*args, **kwargs)
        with open(output, "a") as other_seat:  # another writer lands right after the read
            other_seat.write("attempt\n")
        return data

    monkeypatch.setattr(pi, "_seat_provider_source", lambda *_: ("codex", "/usr/bin/true"))
    with _profile_with_a_secret(tmp_path, output):
        monkeypatch.setattr(pi, "read_seat_output", read_then_a_concurrent_write)
    assert output.read_text() == "attempt\n"


def test_an_output_holding_a_copied_secret_is_still_redacted(tmp_path, monkeypatch):
    output = tmp_path / "out"
    monkeypatch.setattr(pi, "_seat_provider_source", lambda *_: ("codex", "/usr/bin/true"))
    with _profile_with_a_secret(tmp_path, output):
        output.write_text("leaked synthetic-access-token here\n")
    assert output.read_text() == "leaked [credential redacted] here\n"
