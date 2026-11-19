"""One place that talks to language models, with automatic backup.

Order tried:
  1. OpenRouter (hackathon credits)  -> needs OPENROUTER_API_KEY
  2. Gemini (Google AI Studio / Vertex AI) -> needs GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT
If every provider fails, the caller gets an exception and the app falls back to a SAFE
DEFAULT (HOLD / needs human review). It never guesses.

Keys come from environment variables or a local .env file (never commit .env).
"""
import json
import os
import re
import urllib.error
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-5"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def load_dotenv(path=os.path.join(os.path.dirname(__file__), "..", ".env")):
    """Tiny .env reader: KEY=value lines. Existing environment variables win."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


def openrouter_available():
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def gemini_available():
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_API_KEY"))


def available():
    return openrouter_available() or gemini_available()


def _parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def _check_required(obj, schema):
    missing = [k for k in schema.get("required", []) if k not in obj]
    if missing:
        raise ValueError(f"model answer missing fields: {missing}")
    return obj


def call_openrouter(prompt, schema, model=None, timeout=25):
    model = model or os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Reply with ONE JSON object only, no other text. "
                                          "It must match this JSON schema (types in uppercase are JSON types):\n"
                                          + json.dumps(schema)},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
        "X-Title": "SkyGuard FL (Florida Poly hackathon)",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return _check_required(_parse_json(data["choices"][0]["message"]["content"]), schema), f"openrouter:{model}"


def call_gemini(prompt, schema, model=None):
    from google import genai
    from google.genai import types

    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"],
                              location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    else:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_schema=schema, temperature=0))
    return _check_required(json.loads(resp.text), schema), f"gemini:{model}"


def extract_json(prompt, schema):
    """Tries each configured provider in order. Returns (dict, label saying who answered)."""
    errors = []
    if openrouter_available():
        try:
            return call_openrouter(prompt, schema)
        except urllib.error.HTTPError as e:
            reason = "credits used up" if e.code == 402 else f"HTTP {e.code}"
            errors.append(f"OpenRouter: {reason}")
        except Exception as e:
            errors.append(f"OpenRouter: {e}")
    if gemini_available():
        try:
            out, label = call_gemini(prompt, schema)
            return out, label + (f" (backup; {errors[0]})" if errors else "")
        except Exception as e:
            errors.append(f"Gemini: {e}")
    raise RuntimeError("; ".join(errors) or "no AI provider configured")
