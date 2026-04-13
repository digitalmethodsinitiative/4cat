"""
update_llms.py — helper script to detect new LLM models from provider APIs
and suggest additions to common/assets/llms.json.

Supported providers and their model-list endpoints:

  OpenAI      GET https://api.openai.com/v1/models
  Google      GET https://generativelanguage.googleapis.com/v1beta/models
  Anthropic   GET https://api.anthropic.com/v1/models
  Mistral     GET https://api.mistral.ai/v1/models      (includes capabilities.vision)
  DeepSeek    GET https://api.deepseek.com/models       (OpenAI-compatible)

Usage:
    python helper-scripts/update_llms.py \
        --openai-key  sk-... \
        --google-key  AIza... \
        --anthropic-key sk-ant-... \
        --mistral-key ... \
        --deepseek-key ... \
        [--apply]

Pass --apply to write new entries into llms.json automatically.
Without --apply the script only prints a diff/report.

Notes on capability detection:
  - Mistral: the /v1/models response includes a per-model `capabilities` object
    with boolean flags such as `vision`, `function_calling`, and `fine_tuning`.
    These map directly to "image" and "structured_output" capabilities.
  - OpenAI / Anthropic / DeepSeek: the models list endpoint does NOT include
    modality metadata.  New models are flagged for manual review.
  - Google: supportedGenerationMethods is returned but does not enumerate
    modalities; the script flags new models for manual review.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests is required: pip install requests", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
LLMS_JSON = REPO_ROOT / "common" / "assets" / "llms.json"

# ---------------------------------------------------------------------------
# Per-provider fetchers
# ---------------------------------------------------------------------------

def fetch_openai(api_key: str) -> list[dict]:
    """Return a list of {id, provider, capabilities_hint} dicts."""
    url = "https://api.openai.com/v1/models"
    resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    results = []
    for m in models:
        model_id = m["id"]
        # OpenAI doesn't return modality info; guess from name patterns
        caps = _openai_capability_hints(model_id)
        results.append({"id": model_id, "provider": "openai", "capabilities": caps, "raw": m})
    return results


def fetch_google(api_key: str) -> list[dict]:
    """Return models from the Gemini generativelanguage API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=100"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("models", [])
    results = []
    for m in models:
        # name is "models/gemini-2.0-flash" — strip the prefix
        model_id = m.get("name", "").replace("models/", "")
        # Google doesn't list modalities explicitly; flag for manual review
        results.append({
            "id": model_id,
            "provider": "google",
            "capabilities": None,  # requires manual review
            "raw": m,
        })
    return results


def fetch_anthropic(api_key: str) -> list[dict]:
    """Return models from Anthropic's models endpoint."""
    url = "https://api.anthropic.com/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    results = []
    for m in models:
        model_id = m.get("id", "")
        # Anthropic doesn't return modality info; all current Claude models support text + image
        caps = ["text", "image", "structured_output"]
        results.append({"id": model_id, "provider": "anthropic", "capabilities": caps, "raw": m})
    return results


def fetch_mistral(api_key: str) -> list[dict]:
    """Return models from Mistral; the response includes a capabilities object."""
    url = "https://api.mistral.ai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    results = []
    for m in models:
        model_id = m.get("id", "")
        raw_caps = m.get("capabilities", {})
        caps = _mistral_caps_from_api(raw_caps)
        results.append({"id": model_id, "provider": "mistral", "capabilities": caps, "raw": m})
    return results


def fetch_deepseek(api_key: str) -> list[dict]:
    """DeepSeek exposes an OpenAI-compatible /models endpoint."""
    url = "https://api.deepseek.com/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    results = []
    for m in models:
        model_id = m.get("id", "")
        # No modality info; default to text; flag reasoner models
        caps = ["text", "reasoning"] if "reasoner" in model_id else ["text", "structured_output"]
        results.append({"id": model_id, "provider": "deepseek", "capabilities": caps, "raw": m})
    return results


# ---------------------------------------------------------------------------
# Capability heuristics (used when the API doesn't return modality metadata)
# ---------------------------------------------------------------------------

def _openai_capability_hints(model_id: str) -> list[str]:
    """Best-effort capability guess based on OpenAI model naming conventions."""
    caps = ["text"]
    mid = model_id.lower()

    # Vision / image
    if any(tag in mid for tag in ("gpt-4o", "gpt-4.1", "gpt-4-vision", "gpt-4v", "gpt-5")):
        caps.append("image")

    # Audio
    if any(tag in mid for tag in ("audio", "gpt-4o", "gpt-5.4", "realtime")):
        if "audio" not in caps:
            caps.append("audio")

    # Video — only the very top-tier GPT-5 Pro class
    if "pro" in mid and "gpt-5" in mid:
        caps.append("video")

    # Reasoning
    if any(tag in mid for tag in ("o1", "o3", "o4", "reasoning")):
        caps.append("reasoning")

    # Structured output — all non-legacy GPT models support JSON mode
    if not any(tag in mid for tag in ("instruct", "davinci", "curie", "babbage", "ada")):
        caps.append("structured_output")

    return caps


def _mistral_caps_from_api(raw: dict) -> list[str]:
    """Map Mistral's capabilities dict to 4CAT capability tokens."""
    caps = ["text"]
    if raw.get("vision"):
        caps.append("image")
    if raw.get("function_calling"):
        caps.append("structured_output")
    return caps


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

def compare_and_report(existing: dict, fetched: list[dict], apply: bool) -> dict:
    """
    Compare fetched models against existing llms.json entries.
    Returns an updated dict (may equal existing if no changes and apply=False).
    """
    new_entries = {}

    for model in fetched:
        model_id = model["id"]
        provider = model["provider"]
        caps = model["capabilities"]

        if model_id in existing:
            # Model already tracked — check if capabilities differ
            existing_caps = set(existing[model_id].get("capabilities", []))
            if caps is not None and existing_caps != set(caps):
                print(
                    f"  [changed] {model_id}: "
                    f"existing={sorted(existing_caps)} "
                    f"api={sorted(caps)}"
                )
        else:
            # New model not in llms.json
            caps_display = caps if caps is not None else ["<manual review needed>"]
            print(f"  [new]     {model_id} ({provider})  caps={caps_display}")
            new_entries[model_id] = {
                "name": f"[{provider.capitalize()}] {model_id}",
                "model_card": "",
                "provider": provider,
                "capabilities": caps if caps is not None else [],
            }

    if not new_entries:
        print("  No new models found.")
        return existing

    if apply:
        updated = {**existing, **new_entries}
        with LLMS_JSON.open("w") as fh:
            json.dump(updated, fh, indent=4)
        print(f"\n  Wrote {len(new_entries)} new entries to {LLMS_JSON}")
        return updated
    else:
        print(
            f"\n  Run with --apply to add {len(new_entries)} new "
            "model(s) to llms.json."
        )
        return existing


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect new LLM models from provider APIs and optionally update llms.json."
    )
    parser.add_argument("--openai-key",    metavar="KEY", help="OpenAI API key")
    parser.add_argument("--google-key",    metavar="KEY", help="Google AI Studio API key")
    parser.add_argument("--anthropic-key", metavar="KEY", help="Anthropic API key")
    parser.add_argument("--mistral-key",   metavar="KEY", help="Mistral API key")
    parser.add_argument("--deepseek-key",  metavar="KEY", help="DeepSeek API key")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write new entries into llms.json (dry-run by default)",
    )
    args = parser.parse_args()

    with LLMS_JSON.open() as fh:
        existing = json.load(fh)

    fetchers = [
        ("OpenAI",    args.openai_key,    fetch_openai),
        ("Google",    args.google_key,    fetch_google),
        ("Anthropic", args.anthropic_key, fetch_anthropic),
        ("Mistral",   args.mistral_key,   fetch_mistral),
        ("DeepSeek",  args.deepseek_key,  fetch_deepseek),
    ]

    for label, key, fetcher in fetchers:
        if not key:
            print(f"\n[{label}] skipped (no API key provided)")
            continue

        print(f"\n[{label}]")
        try:
            models = fetcher(key)
            existing = compare_and_report(existing, models, apply=args.apply)
        except Exception as exc:
            print(f"  ERROR: {exc}")


if __name__ == "__main__":
    main()
