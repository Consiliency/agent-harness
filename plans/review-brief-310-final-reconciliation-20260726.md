# Final reconciliation check for Consiliency/agent-harness#310 plans

This is not another broad architecture review. Verify only that the latest six-plan
bundle closes these four prior blocking findings without creating a contradiction:

1. effort provenance distinguishes requested, policy-normalized, and final argv
   effort, including truthful Grok max/max/high and Codex max/max/xhigh;
2. both legacy and model-first Claude seats use one subscription scrub/preflight,
   and native fill cannot bypass the TUI contract;
3. repair escalation history requires matching roadmap and phase digests as well
   as phase/executor/fingerprint, and actually-launched blocked repairs count;
4. refusal/fallback/research extensions preserve `PanelLegResult` byte compatibility
   through non-field attachments or an explicitly omitting serializer.

Also confirm the previously added concrete PMCP JSONL audit contract, missing test
suites, and live Firecrawl+Bright Data acceptance remain present. Report only any
remaining load-bearing defect. End with exactly AGREE, PARTIALLY AGREE, or DISAGREE.
