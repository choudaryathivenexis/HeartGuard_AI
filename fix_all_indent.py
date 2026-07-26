"""
Uses Python's AST to reformat broken Python files.
ast.unparse() regenerates syntactically valid Python from the parse tree.
We first fix the critical structural pattern: 'if X:\n    stmt' where stmt
needs to be indented one more level than the if.
"""
import ast, sys, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
FILES = ["app.py", "pages_ext.py", "auth_db.py", "train_models.py"]

def fix_flat_blocks(source):
    """
    Find patterns where a block-starting line (if/else/elif/try/except/finally/
    for/while/with/def/class) is followed by a line at the SAME indent level.
    Insert one extra level of indent on the body lines.
    """
    lines = source.split('\n')
    BLOCK_STARTERS = re.compile(
        r'^(\s*)(if |elif |else:|for |while |with |try:|except|finally:|def |class )'
    )

    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = BLOCK_STARTERS.match(line)

        if m and line.rstrip().endswith(':'):
            current_indent = len(m.group(1))
            result.append(line)
            i += 1

            # Collect body lines that are at same or wrong indent
            # Body should be at current_indent + 4
            expected_indent = current_indent + 4
            j = i
            # Find next non-empty line
            while j < len(lines) and lines[j].strip() == '':
                j += 1

            if j < len(lines):
                body_line = lines[j]
                body_stripped = body_line.lstrip(' ')
                body_indent = len(body_line) - len(body_stripped)

                # If body is at same level as the header → it's broken
                if body_indent == current_indent and body_stripped.strip():
                    # Insert all blank lines between header and body
                    while i < j:
                        result.append(lines[i])
                        i += 1
                    # Now fix the body block
                    # All lines at this same indent that belong to this block
                    while i < len(lines):
                        bline = lines[i]
                        bstripped = bline.lstrip(' ')
                        bindent = len(bline) - len(bstripped)

                        if bline.strip() == '':
                            result.append(bline)
                            i += 1
                            continue

                        # Stop if we've dedented below the header level
                        if bindent < current_indent:
                            break

                        # If at same level as header, this is a mis-indented body line
                        if bindent == current_indent:
                            result.append('    ' + bline)
                        else:
                            result.append(bline)
                        i += 1
                    continue  # already advanced i
        else:
            result.append(line)
        i += 1

    return '\n'.join(result)


def fix_file(fpath):
    with open(fpath, 'r', encoding='utf-8') as f:
        source = f.read()

    # Apply fix multiple passes until stable
    for _ in range(10):
        new_source = fix_flat_blocks(source)
        if new_source == source:
            break
        source = new_source

    with open(fpath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(source)


for fname in FILES:
    fpath = os.path.join(BASE, fname)
    if not os.path.exists(fpath):
        print(f"Skipping: {fname}")
        continue
    print(f"Fixing {fname}...", end=" ", flush=True)
    fix_file(fpath)
    print("done")

print("\nAll done!")
