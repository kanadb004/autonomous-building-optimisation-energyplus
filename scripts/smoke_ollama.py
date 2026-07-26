"""Smoke check: Ollama serves the model, returns JSON, and how long one
completion takes."""

import json
import os
import time

import ollama

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")

PROMPT = (
    "You are a JSON-only API. Given a room temperature of 26.5 C and an "
    "occupied comfort band of 21-24 C, respond with ONLY a JSON object of "
    'the form {"action": "cool" | "heat" | "none", "reasoning": "<one '
    'sentence>"}. No other text.'
)

client = ollama.Client(host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))

start = time.monotonic()
response = client.chat(
    model=MODEL,
    messages=[{"role": "user", "content": PROMPT}],
    format="json",
)
latency = time.monotonic() - start

content = response["message"]["content"]
print(f"Model: {MODEL}")
print(f"Latency: {latency:.2f}s")
print(f"Raw reply: {content}")

parsed = json.loads(content)
assert "action" in parsed, "reply missing 'action' key"
print("SMOKE CHECK PASSED: Ollama returned valid JSON.")
