# CI archive build tooling

The ordinary pytest matrix pins `build==1.6.1` and installs `setuptools>=70.1`
so the frozen CONFORM archive-input test can build its sdist and derived wheel.
This is CI-only verification tooling, not a runtime or release dependency. The
same pins are the `test` dependency group in `phase-loop-runtime/pyproject.toml`.
