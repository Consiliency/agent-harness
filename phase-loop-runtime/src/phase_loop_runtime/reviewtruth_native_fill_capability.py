"""Production marker for the REVIEWTRUTH early slice (native claude seat fill, EC-REVIEWTRUTH-14).

Installed by the slice's implementation landing (PR-2 of plan agent-harness#918). Its presence
makes the slice's falsifiers (``tests/test_native_claude_seat_fill.py``) run without the
``PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH`` flag — the phase plan's forced-then-marker-inert shape.
Deliberately NOT the phase-wide ``reviewtruth_capability`` marker, which the phase plan reserves
for the completion of SL-2 through SL-5.
"""

REVIEWTRUTH_NATIVE_FILL_CAPABILITY_VERSION = "reviewtruth.native-fill.v1"
