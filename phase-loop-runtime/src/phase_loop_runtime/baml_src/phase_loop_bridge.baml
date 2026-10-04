// Host bridge for phase_loop_runtime's BAML worker. Every function returns a
// map<string, string> with exactly one key (ok, error or request), so the
// worker needs no generated typemap.

function phase_loop_parse_closeout(raw: string) -> map<string, string> {
    let v = EmitPhaseCloseout@spec(phase_alias = "", plan_produces = [], plan_owned_files = [], closeout_commit_sha = null)
        .parse(raw) catch (e) {
        baml.errors.ParseError => {
            return { "error": e.message };
        }
    };
    { "ok": baml.json.to_string(v) }
}

function phase_loop_closeout_request(
    phase_alias: string,
    plan_produces: string[],
    plan_owned_files: string[],
    closeout_commit_sha: string?,
) -> map<string, string> {
    let r = EmitPhaseCloseout@spec(
        phase_alias = phase_alias,
        plan_produces = plan_produces,
        plan_owned_files = plan_owned_files,
        closeout_commit_sha = closeout_commit_sha,
    )
        .build_request();
    { "request": baml.json.to_string(r) }
}

function phase_loop_evidence_request(
    tier2_signal_summary: string,
    sample_artifact_content: string,
    expected_artifact_characteristics: string,
) -> map<string, string> {
    let r = EvaluateSuspectedFakeEvidence@spec(
        tier2_signal_summary = tier2_signal_summary,
        sample_artifact_content = sample_artifact_content,
        expected_artifact_characteristics = expected_artifact_characteristics,
    )
        .build_request();
    { "request": baml.json.to_string(r) }
}
