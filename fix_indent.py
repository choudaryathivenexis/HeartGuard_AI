with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Lines 28-33 (0-indexed: 27-32) need indentation fixed
# The function get_bg_b64 has collapsed indentation after emoji removal
# We'll rewrite those lines with proper indentation

fixed_block = [
    'def get_bg_b64():\n',
    '    img_path = os.path.join(BASE_DIR, "heart_bg.png")\n',
    '    if os.path.exists(img_path):\n',
    '        with open(img_path, "rb") as f:\n',
    '            return base64.b64encode(f.read()).decode()\n',
    '    return None\n',
]

# Find the function by scanning for its definition
for i, line in enumerate(lines):
    if line.strip() == 'def get_bg_b64():':
        # Replace lines i through i+5
        lines[i:i+6] = fixed_block
        print(f"Fixed lines {i+1} to {i+6}")
        break
else:
    print("Function not found!")

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done.")
