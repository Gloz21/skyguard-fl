"""Accuracy test for the two AI readers, and a side-by-side model comparison.

  Put OPENROUTER_API_KEY=... in .env, then:
  python eval/eval_ai.py                                   # compares the default models
  python eval/eval_ai.py anthropic/claude-sonnet-5 google/gemini-2.5-flash

Without OpenRouter it tests whatever is configured (e.g. GEMINI_API_KEY) once.
Prints accuracy per model and writes eval/results.json. Put the table on a slide.
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
from campus import CampusDispatch  # noqa: E402
import llm  # noqa: E402
from notam import PROMPT as NOTAM_PROMPT, SCHEMA as NOTAM_SCHEMA, build_closure  # noqa: E402
from campus import INCIDENT_TYPES, PROMPT as INC_PROMPT, schema as inc_schema  # noqa: E402

if not llm.available():
    sys.exit("Put OPENROUTER_API_KEY (or GEMINI_API_KEY) in .env first.")

DEFAULT_MODELS = ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash"]
models = sys.argv[1:] or (DEFAULT_MODELS if llm.openrouter_available() else [None])


def norm(v):
    if isinstance(v, str):
        return v.strip().upper()
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def score(cases, predict, fields):
    per_field = {f: 0 for f in fields}
    exact, rows = 0, []
    for c in cases:
        try:
            pred = predict(c)
        except Exception as e:
            pred = {"error": str(e)}
        ok = {f: norm(pred.get(f)) == norm(c["label"].get(f)) for f in fields}
        for f in fields:
            per_field[f] += ok[f]
        exact += all(ok.values())
        rows.append({"id": c["id"], "correct": ok, "pred": pred})
    n = len(cases)
    return {"n": n, "all_fields_correct": f"{exact}/{n}",
            "per_field": {f: f"{v}/{n}" for f, v in per_field.items()}, "rows": rows}


with open(os.path.join(HERE, "..", "data", "notam_testset.json")) as f:
    notams = json.load(f)["cases"]
with open(os.path.join(HERE, "..", "data", "incident_testset.json")) as f:
    incidents = json.load(f)["cases"]

notam_fields = ["category", "affects_aircraft", "shape", "coord_strings", "center_string",
                "radius_nm", "floor_raw", "ceiling_raw", "start_raw", "end_raw"]
cd = CampusDispatch([])
lm_text = "\n".join(f"  {l['id']}: {l['name']}" for l in cd.landmarks.values())


def ask(prompt, sch, model):
    if model:
        return llm.call_openrouter(prompt, sch, model=model)[0]
    return llm.extract_json(prompt, sch)[0]


results = {}
for model in models:
    name = model or "configured default"
    r1 = score(notams, lambda c: ask(NOTAM_PROMPT.format(text=c["text"]), NOTAM_SCHEMA, model), notam_fields)
    # Safety net: did the code-side checks catch every wrong airspace answer?
    r1["wrong_answers_not_caught_by_validation"] = [
        row["id"] for row, c in zip(r1["rows"], notams)
        if not all(row["correct"].values()) and "error" not in row["pred"]
        and c["label"]["affects_aircraft"] and not build_closure(c["id"], c["text"], row["pred"])["needs_review"]]
    r2 = score(incidents, lambda c: ask(INC_PROMPT.format(types=", ".join(INCIDENT_TYPES), landmarks=lm_text,
                                                          text=c["text"]), inc_schema(list(cd.landmarks)), model),
               ["incident_type", "landmark_id", "surveillance_request"])
    results[name] = {"notam": r1, "incident": r2}

print(f"\n{'Model':34} {'FAA notices':>12} {'Incident reports':>17}  Wrong + not caught")
for name, r in results.items():
    print(f"{name:34} {r['notam']['all_fields_correct']:>12} {r['incident']['all_fields_correct']:>17}  "
          f"{r['notam']['wrong_answers_not_caught_by_validation'] or 'none'}")
with open(os.path.join(HERE, "results.json"), "w") as f:
    json.dump(results, f, indent=2, default=str)
print("\nDetails per field and per case: eval/results.json")
