#!/usr/bin/python3
"""Synthetic offline fixture, never an installed-provider qualification."""
import os
import sys
import time

mode = sys.argv[-1]
if mode == "wait":
    time.sleep(30)
elif mode == "write":
    open("fixture-write", "w").write("synthetic")
elif mode == "stderr":
    os.write(2, b"fixture-stderr-sentinel")
elif mode == "malformed":
    os.write(1, b"not a diff")
elif mode == "fail":
    sys.exit(7)
elif mode == "oversized":
    os.write(1, b"x" * 20000)
if mode in ("patch", "write", "stderr"):
    os.write(1, b"diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new\n")
