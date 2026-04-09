#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restore clean AdhikarAI.py file"""

# Minimal working code to restore
minimal_code = '''# Basic Flask backend
import asyncio
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    print("[INFO] Starting Adhikar AI backend on http://127.0.0.1:5500")
    app.run(debug=True, host="127.0.0.1", port=5500)
'''

# Write with UTF-8 encoding
with open('AdhikarAI.py', 'w', encoding='utf-8') as f:
    f.write(minimal_code)

print("Minimal AdhikarAI.py written successfully")
print(f"File size: {len(minimal_code)} bytes")
