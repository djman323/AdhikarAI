with open('AdhikarAI.py', 'r') as f:
    lines = f.readlines()

# Find lines with @app.route decorator
print("Routes found:")
for i in range(len(lines)):
    if '@app.route' in lines[i]:
        print(f"Line {i+1}: {lines[i].strip()}")

# Also find where function defs start at root level
print("\n\nRoot-level function definitions:")
for i in range(len(lines)):
    if lines[i].startswith('def '):
        print(f"Line {i+1}: {lines[i].strip()[:60]}")

# Find where the last @app.route and its full function ends
print(f"\n\nTotal lines: {len(lines)}")
