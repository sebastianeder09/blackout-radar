"""Sucht in einer Ansicht von "uiautomator dump" ein Element mit diesem Text und gibt die Mitte aus.

  python3 android/test/find_node.py ui.xml "Weiter"   ->   "540 1820"
"""
import re
import sys
import xml.etree.ElementTree as ET

path, wanted = sys.argv[1], sys.argv[2]
best = None
for node in ET.parse(path).iter("node"):
    texts = [node.get("text") or "", node.get("content-desc") or ""]
    exact = any(t.strip() == wanted for t in texts)
    partial = any(wanted in t for t in texts)
    if not (exact or partial):
        continue
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
    if not match:
        continue
    x1, y1, x2, y2 = map(int, match.groups())
    if x2 <= x1 or y2 <= y1:
        continue
    rank = (0 if exact else 1, 0 if node.get("clickable") == "true" else 1)
    if best is None or rank < best[0]:
        best = (rank, f"{(x1 + x2) // 2} {(y1 + y2) // 2}")
if best:
    print(best[1])
else:
    sys.exit(1)
