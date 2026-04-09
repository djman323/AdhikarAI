#!/usr/bin/env python3
# Read the first 1100 lines (good code before duplication)
with open('AdhikarAI.py', 'r') as f:
    lines = f.readlines()

# Keep lines up to 1100
good_lines = lines[:1100]

# Find the last complete function/route (around line 850-1000)
# We'll find the last closing brace of the /chat route
last_good_line = 0
for i in range(1000, 1050):
    if i < len(good_lines) and good_lines[i].strip() and not good_lines[i].startswith(' '):
        # Found a line at root level (not indented)
        last_good_line = i
        break

if last_good_line == 0:
    last_good_line = 1000

print(f"Keeping lines up to {last_good_line}")
print(f"Last preserved line: {repr(good_lines[last_good_line-1:last_good_line])}")

# Truncate to that point
good_lines = good_lines[:last_good_line]

# Add proper ending
ending = '\n\nif __name__ == "__main__":\n    app.run(debug=True, host="127.0.0.1", port=5500)\n'
good_lines.append(ending)

# Write the cleaned file
with open('AdhikarAI.py', 'w') as f:
    f.writelines(good_lines)

print(f"File truncated and fixed. Total lines now: {len(good_lines)}")
