# CI archive build tooling

The ordinary pytest matrix pins `build==1.5.1` and installs `setuptools>=68`
so the frozen CONFORM archive-input test can build its sdist and derived wheel.
This is CI-only verification tooling, not a runtime or release dependency.
Track replacement of the yanked pin in `agent-harness#464`.
