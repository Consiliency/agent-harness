"""Seat egress rules place current host-address restrictions before allowances."""

import json
import subprocess

import pytest

from phase_loop_runtime import sandbox_egress, sandbox_policy


def test_host_addresses_precede_uplink_and_endpoint_allowances():
    policy = sandbox_policy.EgressPolicy(allow=(("203.0.113.10", 8443),))
    rules = sandbox_egress.egress_rules(policy, host_addresses=("203.0.113.10", "10.0.2.15"))
    for address in ("203.0.113.10", "10.0.2.15"):
        deny = next(i for i, rule in enumerate(rules) if address in rule and "REJECT" in rule)
        assert deny < next(i for i, rule in enumerate(rules) if "ACCEPT" in rule)


def test_host_addresses_are_read_again_for_every_build(monkeypatch):
    outputs = iter(["203.0.113.10", "203.0.113.11"])

    def run(argv, **kwargs):
        assert argv[0].startswith("/")
        return subprocess.CompletedProcess(argv, 0, json.dumps([
            {"addr_info": [{"family": "inet", "local": next(outputs)},
                           {"family": "inet6", "local": "2001:db8::1"}]}
        ]), "")

    monkeypatch.setattr(sandbox_egress.subprocess, "run", run)
    assert sandbox_egress.host_addresses() == ("203.0.113.10", "2001:db8::1")
    assert sandbox_egress.host_addresses() == ("203.0.113.11", "2001:db8::1")


def test_host_address_inventory_refuses_invalid_data(monkeypatch):
    monkeypatch.setattr(sandbox_egress.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, "not-json", ""))
    with pytest.raises(sandbox_egress.EgressUnavailable):
        sandbox_egress.host_addresses()


def test_ipv6_rules_have_explicit_default_deny():
    rules = sandbox_egress.ipv6_egress_rules(("2001:db8::1",))
    assert rules[-1] == "-P OUTPUT DROP"
    assert any("2001:db8::1" in rule and "REJECT" in rule for rule in rules)
    assert not any("ACCEPT" in rule and "ipv6-icmp" not in rule for rule in rules)


def test_qualification_observer_reads_the_held_network_policy():
    from phase_loop_runtime import agy_qualification, panel_invoker

    with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
        pid = int(prefix[prefix.index('-t') + 1])
        report = agy_qualification.inspect_network(pid)
    assert report['network_rules_verified'] is True
    assert report['sandbox_network_filtered'] is True
    assert report['network_rule_checks'] > 0
    assert panel_invoker._EGRESS_LAUNCH_PREFIX.get() == ()


def test_network_helper_probe_ignores_candidate_path_entries(tmp_path, monkeypatch):
    import os

    marker = tmp_path / 'unselected-helper-ran'
    planted = tmp_path / 'unshare'
    planted.write_text('#!/bin/sh\nprintf called > ' + str(marker) + '\nexit 0\n')
    planted.chmod(0o700)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    sandbox_egress.egress_isolation_available()
    assert not marker.exists()


def test_qualification_observer_uses_a_trusted_child_path(tmp_path, monkeypatch):
    import os
    from phase_loop_runtime import agy_qualification

    marker = tmp_path / 'unselected-helper-ran'
    planted = tmp_path / 'iptables'
    planted.write_text('#!/bin/sh\nprintf called > ' + str(marker) + '\nexit 1\n')
    planted.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    with sandbox_egress.isolated_network(timeout_s=None, required=True) as prefix:
        report = agy_qualification.inspect_network(int(prefix[prefix.index('-t') + 1]))
    assert report['network_rules_verified'] and not marker.exists()


def test_owned_provider_view_keeps_dns_tls_and_ipv6_policy(tmp_path, owned_review_network):
    import os
    from pathlib import Path
    from phase_loop_runtime import panel_invoker
    from phase_loop_runtime.review_stage import trusted_host_executable

    prefix = panel_invoker._EGRESS_LAUNCH_PREFIX.get()
    holder = prefix[prefix.index('-t') + 1]
    slirp = []
    for child in Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text().split():
        argv = Path(f'/proc/{child}/cmdline').read_bytes().split(b'\0')
        if argv and Path(os.fsdecode(argv[0])).name == 'slirp4netns' and holder.encode() in argv:
            slirp.append((child, argv))
    assert len(slirp) == 1
    pid, argv = slirp[0]
    assert b'--enable-sandbox' in argv and b'--enable-seccomp' in argv
    status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines())
    assert status['Seccomp'].strip() == '2'
    admin = prefix[:prefix.index(trusted_host_executable('setpriv'))]
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(())
    try:
        rules = panel_invoker.run_provider(
            [*admin, trusted_host_executable('ip6tables'), '-S', 'OUTPUT'],
            capture_output=True, text=True, check=True,
        ).stdout
        assert '-P OUTPUT DROP' in rules
        injected = panel_invoker.run_provider(
            [*admin, trusted_host_executable('ip'), '-6', 'route', 'add', 'default', 'dev', 'tap0'],
            capture_output=True, text=True,
        )
        assert injected.returncode == 0, injected.stderr
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    source = '''
import ipaddress,json,socket,ssl
host='cloudcode-pa.googleapis.com'
addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
assert addresses
with socket.create_connection((host,443),timeout=10) as raw:
 with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as secure:
  assert secure.getpeercert()
global_v6=[line for line in open('/proc/net/if_inet6')
           if ipaddress.IPv6Address(int(line.split()[0],16)).is_global]
assert not global_v6
print(json.dumps({'dns':True,'tls':True,'global_ipv6':False}))
'''
    result = panel_invoker._run_leg_with_liveness(
        ['/usr/bin/python3', '-I', '-S', '-c', source], cwd=tmp_path,
        env={'PATH': '/usr/bin:/bin'}, deadline_s=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'dns': True, 'tls': True, 'global_ipv6': False}
