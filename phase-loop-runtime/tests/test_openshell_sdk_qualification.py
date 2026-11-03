"""Stock provenance and fork retirement guards; these do not qualify an SDK."""
import ast
import base64
from pathlib import Path

from google.protobuf import descriptor_pb2

from _openshell_channel_server import STOCK_EXEC_DESCRIPTOR, stock_bindings


ROOT = Path(__file__).resolve().parents[1]


def test_fork_qualification_entrypoints_are_retired():
    for relative in (
        'scripts/qualify_openshell_sdk.py',
        'scripts/openshell-sdk-manifest.json',
        'tests/_openshell_qualification.py',
    ):
        assert not (ROOT / relative).exists(), relative
        # Gate A supplies tests as data without its executable script.
        sparse_list = ROOT / 'scripts/gate_a_cleanroom.sh'
        if sparse_list.is_file():
            assert relative not in sparse_list.read_text()


def test_no_runtime_or_stock_helper_private_rpc_or_fork_sdk_dependency():
    retired = ('CancellationLease', 'openshell_pb2',
               'OPENSHELL_GENERATED_DIR',
               'OPENSHELL_SDK_QUALIFICATION', 'qualify_openshell_sdk',
               '_openshell_qualification')
    paths = list((ROOT / 'src/phase_loop_runtime').rglob('*.py'))
    paths.append(ROOT / 'tests/_openshell_channel_server.py')
    for path in paths:
        # Inspect executable identifiers/imports/string constants, excluding comments.
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            values = []
            if isinstance(node, ast.Name):
                values.append(node.id)
            elif isinstance(node, ast.Attribute):
                values.append(node.attr)
            elif isinstance(node, ast.Import):
                values.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                values.append(node.module or '')
                values.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.append(node.value)
            assert not any(token in value for token in retired for value in values), path


def test_stock_descriptor_preserves_exec_wire_contract():
    files = descriptor_pb2.FileDescriptorSet.FromString(
        base64.b64decode(STOCK_EXEC_DESCRIPTOR))
    assert {file.name for file in files.file} == {'datamodel.proto', 'openshell.proto'}
    stock = next(file for file in files.file if file.name == 'openshell.proto')
    method, = stock.service[0].method
    assert (stock.package, stock.service[0].name, method.name) == (
        'openshell.v1', 'OpenShell', 'ExecSandbox')
    assert not method.client_streaming and method.server_streaming
    assert method.input_type == '.openshell.v1.ExecSandboxRequest'
    assert method.output_type == '.openshell.v1.ExecSandboxEvent'
    request = stock_bindings().ExecSandboxRequest.DESCRIPTOR
    assert request.fields_by_name['request_id'].number == 11
    assert request.fields_by_name['execution_timeout'].number == 105
    assert request.fields_by_name['execution_timeout'].message_type.full_name == (
        'google.protobuf.Duration')
    assert 5 not in request.fields_by_number
    message = next(m for m in stock.message_type if m.name == 'ExecSandboxRequest')
    assert any(r.start <= 5 < r.end for r in message.reserved_range)
