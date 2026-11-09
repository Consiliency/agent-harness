"""Run the real ``placement_cli.main`` in its own process against the fake coordinator.

argv: ``<package src> <this fixtures dir> <behaviour.json> -- <placement CLI argv...>``. The
fake coordinator is registered through the public backend registry (the same seam an
optional extra uses); nothing else in the CLI is replaced.
"""

import sys

if __name__ == "__main__":
    source, fixtures, behaviour, separator, *arguments = sys.argv[1:]
    assert separator == "--"
    sys.path[:0] = [source, fixtures]
    from fake_coordinator import register
    from phase_loop_runtime import placement_cli

    register(behaviour)
    raise SystemExit(placement_cli.main(arguments))
