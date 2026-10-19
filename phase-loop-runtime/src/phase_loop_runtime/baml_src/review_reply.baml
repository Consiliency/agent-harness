// The source of review structure. Nullable fields are required explicitly by
// the strict host precheck; BAML parsing is followed by exact tree comparison.
enum ReviewStatusV1 {
    COMPLETE,
    INCOMPLETE,
}

enum ReviewVerdictV1 {
    AGREE,
    PARTIALLY_AGREE,
    DISAGREE,
}

enum ReviewSeverityV1 {
    BLOCKING,
    NON_BLOCKING,
}

enum ReviewEvidenceBasisV1 {
    OBSERVED,
    INSPECTED,
    SUPPLIED,
    REASONED,
}

enum ReviewCoverageStatusV1 {
    ANSWERED,
    NOT_ASSESSED,
}

enum ReviewDecisionKindV1 {
    ACCEPT,
    REVISE,
}

enum ReviewDispositionStatusV1 {
    RESOLVED,
    OPEN,
    DEFERRED,
}

class ReviewFalsifierV1 {
    nodeid: string,
    diff: string,
}

class ReviewEvidenceV1 {
    basis: ReviewEvidenceBasisV1,
    description: string,
    reference: string?,
}

class ReviewFindingV1 {
    id: string,
    severity: ReviewSeverityV1,
    title: string,
    explanation: string,
    requested_change: string,
    obligation_refs: string[],
    evidence: ReviewEvidenceV1[],
    falsifier: ReviewFalsifierV1?,
}

class ReviewCoverageV1 {
    question_id: string,
    status: ReviewCoverageStatusV1,
    answer: string,
    finding_ids: string[],
}

class ReviewReplyV1 {
    schema_version: string,
    request_binding: string,
    review_status: ReviewStatusV1,
    verdict: ReviewVerdictV1?,
    summary: string,
    scope_reviewed: string[],
    findings: ReviewFindingV1[],
    coverage: ReviewCoverageV1[],
    limitations: string[],
}

class ReviewDispositionV1 {
    finding_key: string,
    status: ReviewDispositionStatusV1,
    rationale: string,
    evidence: ReviewEvidenceV1[],
}

class ReviewDecisionV1 {
    schema_version: string,
    request_binding: string,
    review_status: ReviewStatusV1,
    decision: ReviewDecisionKindV1?,
    summary: string,
    dispositions: ReviewDispositionV1[],
    limitations: string[],
}

function EmitReviewReply(request_json: string) -> ReviewReplyV1 {
    client: PhaseLoopCloseoutClient
    prompt: `
        Return one JSON review object for this frozen coordinator request:
        ${request_json}
        ${ctx.output_format()}
    `
}

function EmitReviewDecision(request_json: string) -> ReviewDecisionV1 {
    client: PhaseLoopCloseoutClient
    prompt: `
        Return one JSON president decision for this frozen coordinator request:
        ${request_json}
        ${ctx.output_format()}
    `
}
