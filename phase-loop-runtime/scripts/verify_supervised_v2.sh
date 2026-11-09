#!/usr/bin/env bash
# Source-only, locked-environment verification; installs belong to the caller.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$repo_root"
python="$repo_root/phase-loop-runtime/.venv/bin/python"
[[ -x "$python" ]] || { echo 'locked_python_missing' >&2; exit 2; }
export PYTHONPATH="$repo_root/phase-loop-runtime/src:$repo_root/phase-loop-runtime/tests"
"$python" -I -c 'import pathlib,sys; import phase_loop_runtime.supervised_contracts as m; assert pathlib.Path(m.__file__).resolve() == pathlib.Path(sys.argv[1]).resolve(); print("isolated source provenance:", sys.executable, m.__file__)' "$repo_root/phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py"
case "${1:-}" in
V0) files=('phase-loop-runtime/tests/test_supervised_contracts.py' 'phase-loop-runtime/tests/test_supervised_contracts_vectors.py' 'phase-loop-runtime/tests/test_supervised_contracts_mutations.py' 'phase-loop-runtime/tests/test_supervised_contracts_receipt.py' 'phase-loop-runtime/tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest' 'phase-loop-runtime/tests/test_ci_chronology_scope.py' 'phase-loop-runtime/tests/test_ci_offload_lock.py');;
V1) files=('phase-loop-runtime/tests/test_supervised_envelope_v2.py' 'phase-loop-runtime/tests/test_supervised_capture_v2.py' 'phase-loop-runtime/tests/test_supervised_launch.py' 'phase-loop-runtime/tests/test_supervised_launch_binding.py' 'phase-loop-runtime/tests/test_supervised_launch_route.py' 'phase-loop-runtime/tests/test_supervised_launch_mutations.py' 'phase-loop-runtime/tests/test_supervised_launch_receipt.py');;
V2) files=('phase-loop-runtime/tests/test_supervised_worker.py' 'phase-loop-runtime/tests/test_supervised_worker_cli.py' 'phase-loop-runtime/tests/test_supervised_worker_receipt.py' 'phase-loop-runtime/tests/test_run_status.py' 'phase-loop-runtime/tests/test_run_status_projection.py' 'phase-loop-runtime/tests/test_run_status_receipt.py' 'phase-loop-runtime/tests/test_convergence_adapters.py' 'phase-loop-runtime/tests/test_output_retention.py' 'phase-loop-runtime/tests/test_executable_dependency_startup.py' 'phase-loop-runtime/tests/test_stamp_evidence_receipt.py' 'phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py' 'phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py' 'phase-loop-runtime/tests/test_seat_reference_inventory.py');;
V3) files=('phase-loop-runtime/tests/test_supervised_v2_readiness.py');;
all) files=('phase-loop-runtime/tests/test_supervised_contracts.py' 'phase-loop-runtime/tests/test_supervised_contracts_vectors.py' 'phase-loop-runtime/tests/test_supervised_contracts_mutations.py' 'phase-loop-runtime/tests/test_supervised_contracts_receipt.py' 'phase-loop-runtime/tests/test_gate_a_wheel_isolation.py::GateAConformEvidenceScopeTest' 'phase-loop-runtime/tests/test_ci_chronology_scope.py' 'phase-loop-runtime/tests/test_ci_offload_lock.py' 'phase-loop-runtime/tests/test_supervised_envelope_v2.py' 'phase-loop-runtime/tests/test_supervised_capture_v2.py' 'phase-loop-runtime/tests/test_supervised_launch.py' 'phase-loop-runtime/tests/test_supervised_launch_binding.py' 'phase-loop-runtime/tests/test_supervised_launch_route.py' 'phase-loop-runtime/tests/test_supervised_launch_mutations.py' 'phase-loop-runtime/tests/test_supervised_launch_receipt.py' 'phase-loop-runtime/tests/test_supervised_worker.py' 'phase-loop-runtime/tests/test_supervised_worker_cli.py' 'phase-loop-runtime/tests/test_supervised_worker_receipt.py' 'phase-loop-runtime/tests/test_run_status.py' 'phase-loop-runtime/tests/test_run_status_projection.py' 'phase-loop-runtime/tests/test_run_status_receipt.py' 'phase-loop-runtime/tests/test_convergence_adapters.py' 'phase-loop-runtime/tests/test_output_retention.py' 'phase-loop-runtime/tests/test_executable_dependency_startup.py' 'phase-loop-runtime/tests/test_stamp_evidence_receipt.py' 'phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py' 'phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py' 'phase-loop-runtime/tests/test_seat_reference_inventory.py' 'phase-loop-runtime/tests/test_supervised_v2_readiness.py');;
*) echo 'verification_group_invalid' >&2; exit 2;;
esac
for file in "${files[@]}"; do
  [[ -f "${file%%::*}" ]] || { echo 'verification_input_missing' >&2; exit 2; }
done
limit=900
[[ "$1" != all ]] || limit=1800
exec timeout "$limit" "$python" -m pytest -q -p no:cacheprovider "${files[@]}" "${@:2}"
