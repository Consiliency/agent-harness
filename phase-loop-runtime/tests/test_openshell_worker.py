"""Synthetic adapter only. Its process separation is explicitly NOT isolation."""
import base64
import json
import os
import sys
import threading
import time

import pytest

from phase_loop_runtime.openshell_artifacts import Bound, Refused, canonical, run_process, validate_result
from phase_loop_runtime.openshell_worker import ProviderResult, read_request, run_worker, seal_request
from test_openshell_artifacts import bound as bound, bundle as bundle, limits as limits, repository as repository


TOKEN = "synthetic-test-access-token-no-live-credentials"


def login(expires=None):
    return canonical({"claudeAiOauth": {"accessToken": TOKEN,
                      "expiresAt": (time.time() + 120 if expires is None else expires) * 1000,
                      "scopes": ["user:inference"], "subscriptionType": "synthetic"}})


def seal(bundle, **changes):
    args = dict(nonce="2" * 32, generation="generation-one", image_sha256="4" * 64,
                task="Edit the owned file", tests=("synthetic-content-check",),
                must_end_within_s=10, login_store=login(), request_cap=50000)
    args.update(changes)
    return seal_request(bundle, **args)


class SyntheticRuntime:
    def __init__(self, tmp_path, *, behavior="success"):
        self.behavior = behavior
        script = tmp_path / "synthetic_provider.py"
        script.write_text('''import json, os, pathlib, sys, time
fd = int(os.environ['CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR'])
token = os.read(fd, 4096).decode()
assert not os.read(fd, 1)
assert token not in str(sys.argv)
assert token not in str(dict(os.environ))
assert 'PYTHONPATH' not in os.environ
assert not pathlib.Path('.git').exists()
assert sys.stdin.read() == 'Edit the owned file'
pathlib.Path('owned.txt').write_bytes(b'after\\x00binary\\xff\\n')
print(json.dumps(dict(type='system', subtype='init', apiKeySource='none', session_id='native-session')), flush=True)
print(token, file=sys.stderr)
print(json.dumps(dict(type='result', subtype='success', is_error=False, session_id='native-session', result=token)), flush=True)
''')
        self.provider_program = (sys.executable, "-I", str(script))
        self.test_calls = 0

    def provider(self, launch, bound, cap):
        assert len(launch.pass_fds) == 1
        assert TOKEN not in repr(launch)
        if self.behavior == "wait":
            argv = (sys.executable, "-I", "-c", "import time; time.sleep(30)")
        elif self.behavior == "oversize":
            argv = (sys.executable, "-I", "-c", "import os; os.write(1, b'x'*400000)")
        else:
            argv = launch.argv
        code, out, err = run_process(argv, cwd=launch.cwd, env=launch.env, data=launch.stdin,
                                     cap=cap, bound=bound, pass_fds=launch.pass_fds)
        if self.behavior == "secret-file":
            (launch.cwd / "owned.txt").write_text(TOKEN)
        if self.behavior == "escape":
            (launch.cwd / "other.txt").write_text("changed")
        if self.behavior == "metadata":
            (launch.cwd / ".git").mkdir()
            (launch.cwd / ".git/config").write_text("untrusted")
        if self.behavior == "bad-witness":
            out = out.replace(b'"success"', b'"error"')
        if self.behavior == "truncated":
            out = out[:-1]
        return ProviderResult(code, out, err, self.behavior != "not-quiescent")

    def test(self, work, home, tests, bound, cap):
        self.test_calls += 1
        assert tests == ("synthetic-content-check",)
        if self.behavior in ("secret-file", "escape", "metadata", "tests-failed"):
            return self.behavior != "tests-failed"
        # Only this installed synthetic check is executed. No returned command,
        # repository test or arbitrary request test selector reaches a host shell.
        code, _, _ = run_process((sys.executable, "-I", "-c",
                                 "from pathlib import Path; assert Path('owned.txt').read_bytes() == b'after\\x00binary\\xff\\n'"),
                                cwd=work, env={"HOME": str(home)}, data=b"", cap=cap, bound=bound)
        return code == 0


def test_fake_edits_tests_returns_quarantined_binary(bundle, tmp_path, bound, monkeypatch):
    identity, wire = seal(bundle)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-ambient-key")
    monkeypatch.setenv("PYTHONPATH", "/untrusted/repository/imports")
    runtime = SyntheticRuntime(tmp_path)
    envelope = run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=runtime,
                          scratch_parent=tmp_path, cancelled=lambda: False)
    assert TOKEN.encode() not in envelope
    decoded = json.loads(envelope)
    assert b"[REDACTED]" in base64.b64decode(decoded["native"])
    assert runtime.test_calls == 1
    patch = validate_result(identity, envelope, bundle, tmp_path / "q", bound)
    assert b"GIT binary patch" in patch.path.read_bytes()
    assert not list(tmp_path.glob("implementation-*"))


@pytest.mark.parametrize("behavior,code", [("bad-witness", "native_unsuccessful"),
                                          ("truncated", "witness_truncated"),
                                          ("not-quiescent", "provider_incomplete"),
                                          ("secret-file", "credential_in_artifact"),
                                          ("escape", "ownership_escape"),
                                          ("metadata", "metadata_modified"),
                                          ("tests-failed", "tests_failed"),
                                          ("oversize", "output_limit")])
def test_worker_refusals(bundle, tmp_path, behavior, code):
    identity, wire = seal(bundle)
    with pytest.raises(Refused, match=code) as caught:
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=SyntheticRuntime(tmp_path, behavior=behavior),
                   scratch_parent=tmp_path, cancelled=lambda: False)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("kind", ["expired", "infinite", "missing", "not-subscription", "refresh-only"])
def test_credentials_require_finite_first_party_login(bundle, kind):
    value = json.loads(login())
    oauth = value["claudeAiOauth"]
    if kind == "expired":
        oauth["expiresAt"] = 0
    elif kind == "infinite":
        oauth["expiresAt"] = float("inf")
    elif kind == "missing":
        del oauth["expiresAt"]
    elif kind == "not-subscription":
        oauth["scopes"] = []
    else:
        oauth["refreshToken"] = oauth.pop("accessToken")
    with pytest.raises(Refused):
        seal(bundle, login_store=json.dumps(value).encode())


def test_request_tamper_and_no_default_execution(bundle, tmp_path):
    identity, wire = seal(bundle)
    value = json.loads(wire)
    value["metadata"]["task"] = "tampered"
    with pytest.raises(Refused):
        read_request(canonical(value), bundle, 50000)
    with pytest.raises(Refused, match="isolation_adapter_unavailable"):
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=None,
                   scratch_parent=tmp_path, cancelled=lambda: False)
    assert not list(tmp_path.glob("implementation-*"))


@pytest.mark.parametrize("end", [None, 0, -1, float("inf"), float("nan"), True])
def test_invalid_deadlines(bundle, end):
    with pytest.raises(Refused):
        seal(bundle, must_end_within_s=end)


def test_cancel_and_finite_end(bundle, tmp_path):
    identity, wire = seal(bundle, must_end_within_s=0.3)
    start = time.monotonic()
    with pytest.raises(Refused, match="end_reached"):
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=SyntheticRuntime(tmp_path, behavior="wait"),
                   scratch_parent=tmp_path, cancelled=lambda: False)
    assert time.monotonic() - start < 2
    event = threading.Event()
    event.set()
    identity, wire = seal(bundle)
    with pytest.raises(Refused, match="cancelled"):
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=SyntheticRuntime(tmp_path),
                   scratch_parent=tmp_path, cancelled=event.is_set)


def test_descendant_holding_pipes_cancelled(tmp_path):
    event = threading.Event()
    timer = threading.Timer(0.2, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(Refused, match="cancelled"):
            run_process((sys.executable, "-I", "-c",
                         "import os,time; pid=os.fork(); time.sleep(30) if pid == 0 else os._exit(0)"),
                        cwd=tmp_path, env={}, data=b"", cap=1024,
                        bound=Bound(time.monotonic() + 5, event.is_set))
    finally:
        timer.cancel()
    assert time.monotonic() - started < 2


def test_closed_inherited_descriptor(tmp_path):
    fd = os.open(tmp_path / "journal", os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(fd, True)
    try:
        rc, out, _ = run_process((sys.executable, "-I", "-c",
                                 f"import os\ntry: os.fstat({fd})\nexcept OSError: print('closed')"),
                                cwd=tmp_path, env={}, data=b"", cap=1024,
                                bound=Bound(time.monotonic() + 5, lambda: False))
    finally:
        os.close(fd)
    assert rc == 0 and out == b"closed\n"


def test_committed_request_identity_must_match(bundle, tmp_path):
    from dataclasses import replace
    identity, wire = seal(bundle)
    with pytest.raises(Refused, match="committed_identity_mismatch"):
        run_worker(wire, bundle, expected_identity=replace(identity, generation="other-generation"),
                   request_cap=50000, runtime=SyntheticRuntime(tmp_path), scratch_parent=tmp_path,
                   cancelled=lambda: False)
    assert not list(tmp_path.glob("implementation-*"))


def test_credential_expiry_shortens_worker_end(bundle, tmp_path):
    identity, wire = seal(bundle)
    value = json.loads(wire)
    value["credential"]["expires_at"] = time.time() + 0.3
    started = time.monotonic()
    with pytest.raises(Refused, match="end_reached"):
        run_worker(canonical(value), bundle, expected_identity=identity, request_cap=50000,
                   runtime=SyntheticRuntime(tmp_path, behavior="wait"), scratch_parent=tmp_path,
                   cancelled=lambda: False)
    assert time.monotonic() - started < 2


def test_cancellation_after_provider_wins(bundle, tmp_path):
    identity, wire = seal(bundle)
    event = threading.Event()
    runtime = SyntheticRuntime(tmp_path)
    original = runtime.provider
    def provider(launch, bound, cap):
        result = original(launch, bound, cap)
        event.set()
        return result
    runtime.provider = provider
    with pytest.raises(Refused, match="cancelled"):
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=runtime,
                   scratch_parent=tmp_path, cancelled=event.is_set)
    assert runtime.test_calls == 0


@pytest.mark.parametrize("field", ["nonce", "generation", "image_sha256"])
def test_invalid_identity_types_refused(bundle, field):
    identity, wire = seal(bundle)
    value = json.loads(wire)
    value["metadata"][field] = 123
    with pytest.raises(Refused, match="identity_invalid"):
        read_request(canonical(value), bundle, 50000)


def test_expired_request_never_calls_provider(bundle, tmp_path):
    identity, wire = seal(bundle)
    value = json.loads(wire)
    value["credential"]["expires_at"] = time.time() - 1
    with pytest.raises(Refused, match="credential_expired"):
        run_worker(canonical(value), bundle, expected_identity=identity, request_cap=50000,
                   runtime=SyntheticRuntime(tmp_path), scratch_parent=tmp_path,
                   cancelled=lambda: False)
    assert not list(tmp_path.glob("implementation-*"))


def test_cancellation_during_declared_test_suppresses_result(bundle, tmp_path):
    identity, wire = seal(bundle)
    event = threading.Event()
    runtime = SyntheticRuntime(tmp_path)
    def cancelled_test(*args):
        event.set()
        return True
    runtime.test = cancelled_test
    with pytest.raises(Refused, match="cancelled"):
        run_worker(wire, bundle, expected_identity=identity, request_cap=50000, runtime=runtime,
                   scratch_parent=tmp_path, cancelled=event.is_set)
    assert not list(tmp_path.glob("implementation-*"))
