#!/usr/bin/env python3
"""
headphone.directory pipeline
Generates new product entries via Claude Haiku and pushes to GitHub.
Run manually or via cron.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
import anthropic

# ── config ──────────────────────────────────────────────────────────────────
REPO_DIR = Path("/home/jim/empire/headphone-directory")
DATA_FILE = REPO_DIR / "data.json"
BATCH_SIZE = 10  # products per run
TODAY = date.today().isoformat()

# ── load existing data ───────────────────────────────────────────────────────
def load_existing():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return []

def existing_ids(data):
    return {d["id"] for d in data}

# ── call haiku ───────────────────────────────────────────────────────────────
SYSTEM = """You are a headphone expert building a product directory database.
You return ONLY valid JSON arrays, no markdown, no explanation, no backticks.
All data must be accurate. Prices are approximate street prices in USD."""

PROMPT = """Generate {batch_size} audio products for a directory covering headphones,
IEMs, earbuds (wireless/ANC), headphone amps, and DACs.

Mix the types proportionally:
- headphone-open: open-back over-ear headphones
- headphone-closed: closed-back over-ear headphones  
- iem: in-ear monitors (wired)
- earbud-wireless: true wireless / ANC earbuds
- amp: headphone amplifiers
- dac: DAC units (digital to analog converters)

Avoid these already-listed products: {existing_models}

Return a JSON array where each object has exactly these fields:
{{
  "id": "brand-model-slug-lowercase-hyphens",
  "type": "headphone-open|headphone-closed|iem|earbud-wireless|amp|dac",
  "brand": "Brand Name",
  "model": "Model Name",
  "tagline": "One or two punchy sentences. Direct. No hype. Cover sound signature and who it's for.",
  "price": 000,
  "impedance": 000,
  "sensitivity": 000,
  "driver": "dynamic|planar|electrostatic|balanced-armature|hybrid|null",
  "weight": 000,
  "buy_url": "https://www.amazon.com/s?k=Brand+Model+Name&tag=headphonedirectory-20",
  "released": 0000,
  "added": "{today}"
}}

Notes:
- impedance, sensitivity, weight: use null for amps/DACs and earbuds where not applicable
- driver: use null for amps/DACs
- weight: grams for headphones/IEMs, null for amps/DACs
- buy_url: use Amazon search URL format: https://www.amazon.com/s?k=Brand+Model+Name&tag=headphonedirectory-20 where Brand+Model+Name is the brand and model with spaces replaced by +
- released: year as integer
- tagline: max 2 sentences, no adjective fluff, be direct and opinionated

Return ONLY the JSON array."""

def generate_batch(client, existing_data):
    existing_models = [f"{d['brand']} {d['model']}" for d in existing_data]
    # send only last 50 to keep prompt size manageable
    existing_str = ", ".join(existing_models[-50:]) if existing_models else "none"

    prompt = PROMPT.format(
        batch_size=BATCH_SIZE,
        existing_models=existing_str,
        today=TODAY
    )

    print(f"Calling Haiku for {BATCH_SIZE} new products...")
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=6000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()

    # strip markdown fences if Haiku adds them anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    return json.loads(raw)

# ── deduplicate and merge ────────────────────────────────────────────────────
def merge(existing, new_batch, existing_id_set):
    added = 0
    for item in new_batch:
        if item["id"] in existing_id_set:
            print(f"  skip (duplicate): {item['id']}")
            continue
        existing.append(item)
        existing_id_set.add(item["id"])
        print(f"  + {item['brand']} {item['model']} ({item['type']}) ${item['price']}")
        added += 1
    return added

# ── save and push ────────────────────────────────────────────────────────────
def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} total entries to data.json")

def git_push(added):
    os.chdir(REPO_DIR)
    subprocess.run(["git", "add", "data.json"], check=True)
    subprocess.run(["git", "commit", "-m", f"pipeline: add {added} products ({TODAY})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Pushed to GitHub — Cloudflare Pages deploying...")

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        # try loading from ~/.env
        env_file = Path.home() / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not found in environment or ~/.env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    existing = load_existing()
    id_set = existing_ids(existing)
    print(f"Existing entries: {len(existing)}")

    try:
        new_batch = generate_batch(client, existing)
        print(f"Haiku returned {len(new_batch)} products")
    except json.JSONDecodeError as e:
        print(f"ERROR: Haiku returned invalid JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR calling Haiku: {e}")
        sys.exit(1)

    added = merge(existing, new_batch, id_set)

    if added == 0:
        print("No new products added — all duplicates. Skipping push.")
        return

    save(existing)
    git_push(added)
    print(f"Done. Added {added} new products. Total: {len(existing)}")

if __name__ == "__main__":
    main()
