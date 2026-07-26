with open('app.py', 'rb') as f:
    lines = f.readlines()
for i in range(215, 225):
    raw = lines[i]
    spaces = len(raw) - len(raw.lstrip(b' '))
    text = raw[:60].decode(errors='replace').rstrip()
    print(f'L{i+1}: {spaces}sp | {text}')
