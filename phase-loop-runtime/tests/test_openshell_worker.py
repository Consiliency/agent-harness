"""Synthetic adapter only. Its process separation is explicitly NOT isolation."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from phase_loop_runtime import openshell_worker as ow
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


@pytest.mark.parametrize('vector', json.loads((Path(__file__).parent /
    'data/landlock-exec/manifests.json').read_text())['valid'], ids=lambda v: v['name'])
def test_shared_landlock_manifest_vectors(vector):
    value = vector['input']
    assert ow.landlock_manifest(value['rules'], value['uid'], value['gid']).hex() == vector['hex']


def test_shared_vectors_pin():
    root = Path(__file__).parent / 'data/landlock-exec'
    pin = json.loads((root / 'PIN.json').read_text())
    assert ow.digest((root / 'manifests.json').read_bytes()) == pin['vectors_sha256']
    assert ow.HELPER_SHA256 == pin['helper_sha256']


@pytest.mark.parametrize('vector', ow.json.loads((ow.files('phase_loop_runtime') /
    'contracts/placement/vectors/policies.json').read_text())['valid'], ids=lambda v: v['name'])
def test_stock_policy_vectors(vector):
    assert ow.stock_policy_digest(vector['policy']) == vector['policy_digest']


def test_stock_policy_camelcase_refused_locally():
    policy = ow.review_policy()['policy']
    policy['filesystem']['readOnly'] = policy['filesystem'].pop('read_only')
    with pytest.raises(Refused, match='stock_policy_field'):
        ow.stock_policy_digest(policy)


def test_stock_policy_map_keys_survive():
    policy = ow.review_policy()['policy']
    policy['network_policies']['UserNamedRule'] = {'name': 'unchanged', 'endpoints': []}
    policy['network_middlewares'] = {'MyMiddleware': {'middleware': 'test',
        'config': {'AnyUserKey': {'AnotherKey': 1}}, 'on_error': 'fail_closed'}}
    before = canonical(policy)
    assert ow.stock_policy_digest(policy).startswith('sha256:')
    assert canonical(policy) == before
    policy['network_policies']['UserNamedRule']['unknownField'] = True
    with pytest.raises(Refused):
        ow.stock_policy_digest(policy)


@pytest.mark.parametrize('tamper', ['content', 'manifest', 'mapping', 'projection'])
def test_worker_load_tamper_before_launch(bundle, tmp_path, tamper):
    identity, wire = seal(bundle)
    value = json.loads(wire)
    if tamper == 'content':
        value['load']['content'][0] = 'eA=='
    elif tamper == 'manifest':
        value['load']['source']['files'][0]['sha256'] = '0' * 64
    elif tamper == 'mapping':
        value['load']['guest']['input'] = '/work/escape'
    else:
        value['load']['projections'] = [{'path': '/untrusted'}]
    with pytest.raises(Refused, match='load_digest_mismatch'):
        run_worker(canonical(value), bundle, expected_identity=identity, request_cap=50000,
                   runtime=SyntheticRuntime(tmp_path), scratch_parent=tmp_path, cancelled=lambda: False)
    assert not list(tmp_path.glob('implementation-*'))


def test_content_roundtrip_and_stock_cap(bundle):
    _, wire = seal(bundle)
    assert ow.bundle_from_envelope(wire, 50000) == bundle
    with pytest.raises(Refused, match='request_limit'):
        seal(bundle, task='x' * ow.STOCK_MESSAGE_LIMIT, request_cap=ow.STOCK_MESSAGE_LIMIT * 2)


@pytest.fixture
def guest(bundle, tmp_path, monkeypatch):
    def guest_path(path):
        path = Path(path)
        if path == Path('/work') or Path('/work') in path.parents:
            return tmp_path / path.relative_to('/work')
        return path
    monkeypatch.setattr(ow, 'Path', guest_path)
    helper = tmp_path / 'landlock-exec'
    helper.write_bytes(b'offline fake helper')
    monkeypatch.setattr(ow, 'HELPER', str(helper))
    monkeypatch.setattr(ow, 'HELPER_SHA256', ow.digest(helper.read_bytes()))
    monkeypatch.setattr(ow, 'verify_helper_metadata', lambda: None)
    monkeypatch.setattr(ow.os, 'getuid', lambda: 10001)
    monkeypatch.setattr(ow.os, 'getgid', lambda: 10001)
    monkeypatch.setattr(ow.os, 'geteuid', lambda: 10001)
    monkeypatch.setattr(ow.os, 'getegid', lambda: 10001)
    _, wire = seal(bundle)
    return wire


@pytest.mark.parametrize('abi', [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_guest_abi_order_and_zero_unrestricted_launches(bundle, guest, abi):
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == ow.HELPER
        if argv[1] == '--probe':
            mask = '7fff' if abi < 5 else 'ffff'
            return subprocess.CompletedProcess(argv, 0, f'landlock-exec: abi {abi} supported fs=0x{mask}\n'.encode(), b'')
        assert argv[1] == '--policy' and argv[3] == '--'
        assert Path(argv[2]).read_bytes().startswith(b'LLEXEC01')
        value = json.loads(guest)
        assert ow.scan(ow.Path(value['load']['guest']['input']), bundle.limits,
                       Bound(time.monotonic()+5, lambda: False)) == bundle.files
        assert kwargs['input'] == guest
        return subprocess.CompletedProcess(argv, 126, b'', b'fake restriction failure')
    if abi not in range(3, 9):
        with pytest.raises(Refused, match='landlock_abi_unsupported'):
            ow.load_restrict_exec(guest, bundle, request_cap=50000,
                bound=Bound(time.monotonic()+5, lambda: False), execute=execute)
        assert len(calls) == 1
    else:
        result, record = ow.load_restrict_exec(guest, bundle, request_cap=50000,
            bound=Bound(time.monotonic()+5, lambda: False), execute=execute,
            reclaims=({'reason': 'lease_expired'},))
        assert result.returncode == 126 and len(calls) == 2
        assert record['read_only_enforced_by'] == 'client-landlock'
        assert record['policy_digest'] == ow.review_policy()['policy_digest']
        assert record['reclaims'] == [{'reason': 'lease_expired'}]


@pytest.mark.parametrize('failure', ['cancelled', 'load', 'helper-tamper'])
def test_load_failure_or_cancel_never_launches(bundle, guest, monkeypatch, failure):
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b'landlock-exec: abi 3 supported fs=0x7fff\n', b'')
    if failure == 'load':
        def broken(*args, **kwargs):
            raise OSError('synthetic transfer failure')
        monkeypatch.setattr(ow, 'scan', broken)
    elif failure == 'helper-tamper':
        Path(ow.HELPER).write_bytes(b'tampered')
    with pytest.raises((Refused, OSError)):
        ow.load_restrict_exec(guest, bundle, request_cap=50000,
            bound=Bound(time.monotonic()+5, lambda: failure == 'cancelled'), execute=execute)
    assert all(argv[1] == '--probe' for argv in calls)
    assert len(calls) == (1 if failure == 'load' else 0)


def test_read_only_manifest_never_has_writable_ancestor():
    mapping = {'input': '/work/run/input', 'output': '/work/run/output', 'scratch': '/work/run/scratch'}
    rules = ow.guest_rules(mapping)
    assert ow.landlock_manifest(rules)
    with pytest.raises(Refused, match='manifest_overlap'):
        ow.landlock_manifest(rules + [{'path': '/work', 'role': 'rw', 'type': 'dir'}])


def test_production_entry_refuses_after_restriction_without_adapter(bundle, guest):
    calls = []
    def execute(argv, **kwargs):
        calls.append(argv)
        if argv[1] == '--probe':
            return subprocess.CompletedProcess(argv, 0, b'landlock-exec: abi 8 supported fs=0xffff\n', b'')
        assert argv[:2] == (ow.HELPER, '--policy')
        assert tuple(argv[4:]) == (sys.executable, '-I', '-m', 'phase_loop_runtime.openshell_worker', '--restricted')
        # Fake only the helper's restriction/evidence. Run the actual installed
        # production entry, which has no adapter-selection option or test import.
        return subprocess.run(argv[4:], input=kwargs['input'], capture_output=True,
                              env={'AGENT_TOOLKIT_LANDLOCK': '1:abi=8:fs=0xffff'}, timeout=5)
    result, _ = ow.load_restrict_exec(guest, bundle, request_cap=50000,
        bound=Bound(time.monotonic()+10, lambda: False), execute=execute)
    assert result.returncode == 126
    assert result.stdout == b'' and b'isolation_adapter_unavailable' in result.stderr
    assert len(calls) == 2


def test_production_entry_without_helper_evidence_never_runs_adapter(bundle):
    _, wire = seal(bundle)
    result = subprocess.run((sys.executable, '-I', '-m', 'phase_loop_runtime.openshell_worker', '--restricted'),
                            input=wire, capture_output=True, env={}, timeout=5)
    assert result.returncode == 126 and b'landlock_evidence_missing' in result.stderr


@pytest.mark.parametrize('operation', ['write', 'unlink', 'rename', 'descendant'])
def test_real_shared_helper_readonly_inputs_and_writable_output(tmp_path, operation):
    helper = os.environ.get('LANDLOCK_EXEC_TEST_HELPER')
    if not helper:
        pytest.skip('optional real-kernel helper; fake ABI/load/failure tests always run')
    # Compile the pinned helper separately, without building/pushing an image.
    # uid/gid are the local non-root test user; production always requires 10001.
    probe = subprocess.run((helper, '--probe'), capture_output=True)
    if probe.returncode:
        pytest.skip('host Landlock unavailable: ' + probe.stdout.decode(errors='replace'))
    source, output = tmp_path / 'input', tmp_path / 'output'
    source.mkdir()
    output.mkdir()
    target = source / 'immutable'
    target.write_text('original')
    rules = [{'path': p, 'role': 'ro', 'type': 'dir', 'follow': True}
             for p in ('/usr', '/lib', '/etc')]
    interpreter = Path(sys.executable).resolve()
    rules += [{'path': str(interpreter.parent.parent), 'role': 'ro', 'type': 'dir'}]
    rules += [{'path': str(source), 'role': 'ro', 'type': 'dir'},
              {'path': str(output), 'role': 'rw', 'type': 'dir'}]
    manifest = tmp_path / 'policy'
    manifest.write_bytes(ow.landlock_manifest(rules, os.getuid(), os.getgid()))
    code = '''import os, pathlib, sys
source, output, operation = map(str, sys.argv[1:])
p = pathlib.Path(source) / 'immutable'
if operation == 'descendant':
    pid = os.fork()
    if pid:
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        sys.exit(0)
    operation = 'write'
try:
    if operation == 'write': p.write_text('tamper')
    elif operation == 'unlink': p.unlink()
    else: p.rename(pathlib.Path(output) / 'stolen')
except PermissionError: pass
else: raise AssertionError('read-only control failed')
q = pathlib.Path(output) / 'allowed'
q.write_text('allowed')
q.rename(pathlib.Path(output) / 'renamed')
(pathlib.Path(output) / 'renamed').unlink()
'''
    result = subprocess.run((helper, '--policy', str(manifest), '--', str(interpreter),
                              '-I', '-c', code, str(source), str(output), operation), capture_output=True)
    assert result.returncode == 0, result.stderr
    assert target.read_text() == 'original'


@pytest.mark.parametrize('rules', [[], [{'path': '/a/../b', 'role': 'ro', 'type': 'dir'}],
    [{'path': '/a', 'role': 'rw', 'type': 'dir', 'follow': True}],
    [{'path': '/a', 'role': 'ro', 'type': 'char'}],
    [{'path': '/a', 'role': 'dev', 'type': 'char'}],
    [{'path': '/a', 'role': 'ro', 'type': 'dir'}] * 2])
def test_manifest_builder_refuses_invalid_inputs(rules):
    with pytest.raises(Refused):
        ow.landlock_manifest(rules)


def test_review_image_definition_pins_and_baseline():
    container = (Path(__file__).parents[1] / 'images/review-runner/Containerfile').read_text()
    pin = json.loads((Path(__file__).parent / 'data/landlock-exec/PIN.json').read_text())
    for value in (pin['commit'], pin['helper_sha256'], pin['BUILD.lock_sha256'], pin['toolchain']):
        assert value in container
    assert 'install -d -o 10001 -g 10001 -m 0700 /work' in container
    assert 'USER sandbox:sandbox' in container and 'test ! -e /app' in container
    assert '--chown=0:0 --chmod=0755' in container
    assert 'phase_loop_runtime.openshell_worker' in container


def test_preflight_is_pure_and_refuses_dependency(bundle):
    create = dict(policy=ow.review_policy()['policy'], policy_digest=ow.review_policy()['policy_digest'])
    with pytest.raises(Refused, match='dependency_route_unwired'):
        ow.preflight_worker(bundle, create, task='task', tests=('check',), deadline_s=5,
                            request_cap=50000, generation='generation', dependency_required=True)


def test_bootstrap_preserves_typed_adapter_refusal(bundle, monkeypatch, capsys):
    import io
    _, wire = seal(bundle)
    monkeypatch.setattr(ow.sys, 'stdin', io.TextIOWrapper(io.BytesIO(wire)))
    monkeypatch.setattr(ow.sys, 'argv', ['worker'])
    calls = []
    def restricted(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess([], 126, b'', b'worker refused: isolation_adapter_unavailable\n'), {}
    monkeypatch.setattr(ow, 'load_restrict_exec', restricted)
    assert ow.main() == 126
    assert capsys.readouterr().err == 'worker refused: isolation_adapter_unavailable\n'
    assert len(calls) == 1
