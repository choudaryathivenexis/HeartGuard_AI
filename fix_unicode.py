"""
One-shot fix: replace all non-ASCII characters in train_models.py
with plain ASCII equivalents so it works on Windows cp1252.
"""
import re

REPLACEMENTS = {
    "\u2500": "-",   # BOX DRAWINGS LIGHT HORIZONTAL  ─
    "\u2550": "=",   # BOX DRAWINGS DOUBLE HORIZONTAL ═
    "\u2192": "->",  # RIGHTWARDS ARROW               →
    "\u2190": "<-",  # LEFTWARDS ARROW                ←
    "\u00d7": "x",   # MULTIPLICATION SIGN            x
    "\u2013": "-",   # EN DASH                        -
    "\u2014": "--",  # EM DASH                        —
    "\u2018": "'",   # LEFT SINGLE QUOTATION MARK     '
    "\u2019": "'",   # RIGHT SINGLE QUOTATION MARK    '
    "\u201c": '"',   # LEFT DOUBLE QUOTATION MARK     "
    "\u201d": '"',   # RIGHT DOUBLE QUOTATION MARK    "
}

target = r"train_models.py"

with open(target, encoding="utf-8") as f:
    content = f.read()

# Log what we find
found = {}
for ch, repl in REPLACEMENTS.items():
    count = content.count(ch)
    if count:
        found[ch] = (count, repl)
        content = content.replace(ch, repl)

# Catch any remaining non-ASCII as '?'
remaining = [c for c in content if ord(c) > 127]
if remaining:
    print(f"Still found {len(remaining)} non-ASCII chars (replacing with '?'):")
    for c in set(remaining):
        print(f"  U+{ord(c):04X}")
    content = content.encode("ascii", errors="replace").decode("ascii")

with open(target, "w", encoding="utf-8") as f:
    f.write(content)

print("Done! Replacements made:")
for ch, (count, repl) in found.items():
    print(f"  U+{ord(ch):04X}  x{count}  ->  '{repl}'")
if not found and not remaining:
    print("  (file was already clean)")
