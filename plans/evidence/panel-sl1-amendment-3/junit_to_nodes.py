"""Derive a node list (the committed *.nodes.gz) from a pytest JUnit XML file.

Each line is ``<classname>::<name>\t<pass|fail|skip>``, sorted; a testcase with a
<failure> or <error> child is ``fail``; otherwise one with <skipped> is ``skip``.
"""
import sys
import xml.etree.ElementTree as ET

rows = []
for case in ET.parse(sys.argv[1]).iter("testcase"):
    state = "pass"
    for child in case:
        if child.tag in ("failure", "error"):
            state = "fail"
        elif child.tag == "skipped" and state == "pass":
            state = "skip"
    rows.append(f'{case.get("classname")}::{case.get("name")}\t{state}')
sys.stdout.write("\n".join(sorted(rows)) + "\n")
