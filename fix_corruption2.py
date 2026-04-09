with open('AdhikarAI.py', 'r') as f:
    lines = f.readlines()

# Keep everything up to line 954 (before the helper functions that aren't used)
# The chat route ends somewhere around line 850, and then we have some unused helper functions
# Let's keep up to line 950 and verify it's at a good boundary

# First, find the last complete function/route
keep_lines = lines[:950]

# Add proper closing
closing = '\n\n\nif __name__ == "__main__":\n    print("[INFO] Starting Adhikar AI backend on http://127.0.0.1:5500")\n    app.run(debug=True, host="127.0.0.1", port=5500)\n'
keep_lines.append(closing)

# Write back
with open('AdhikarAI.py', 'w') as f:
    f.writelines(keep_lines)

print(f"File cleaned up. Kept first 950 lines, total now: {len(keep_lines)} lines")
