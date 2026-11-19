# SkyGuard FL

**An AI safety copilot for Florida's new air taxis and Florida Poly's police aircraft.**

Built for the "Cleared for Takeoff: AI for Florida's Skies" hackathon.

> ⚠ Prototype. Flight tracks, notices, weather and locations are **simulated** and labeled that way in the app. A human makes every safety decision.

## The idea
- **Air Taxi Corridor (Tampa ↔ Orlando ↔ Space Coast).** Rocket launches at the Cape close airspace. Gemini reads the FAA's code-like notices, code checks every flight against them and suggests a delay or alternate, and a dispatcher approves.
- **Flight security.** An anomaly model learns what normal flights look like and flags any air taxi that drifts off course, descends unexpectedly or circles. A human chooses what to do: contact, escalate, alert police or dismiss.
- **Campus mode (Astro + the police drone unit).** An officer types what a caller said. Gemini pulls out the incident type, the place and whether it's really a surveillance request. Code works out the ETA, battery needed (Astro has about 20 minutes), wind and airspace for each unit, and an officer picks who goes.

## Where the AI is essential
| AI does | Code does | Human does |
|---|---|---|
| Reads FAA notices and extracts coordinates, altitudes and times | Converts and checks every value against the source text; distance and time math | Approves delays and alternates |
| Learns the normal flight pattern and scores live tracks | Off-route distance and risk level | Contacts, escalates or alerts police |
| Reads incident reports for type, place, urgency and surveillance intent | ETA, battery, wind, airspace, unit ranking | Dispatches, or supervisor approves or denies |

Without the AI there's nothing to put on the map: the notices and reports are free text.

## Responsible AI checklist
- **Grounded facts:** every closure links to its source notice, and every coordinate and time Gemini returns must appear word for word in that text, otherwise it's flagged `NEEDS HUMAN REVIEW`.
- **Calculations in code:** `geo.py`, `conflicts.py` and `campus.py`. Gemini never does math.
- **Human decides:** every action is a button press, logged in the Decision log.
- **Missing or stale data leads to a safe default:** notices older than 30 min put every flight on HOLD, weather older than 60 min grounds the air units, an unreadable notice means HOLD, and an unknown location means HOLD.
- **Uncertainty and timestamps visible:** data age chips, anomaly scores in σ, "read by" labels.
- **Inputs validated and prompt injection tested:** test cases `FDC 6/6001` and `INC-8` contain injection attempts; the size limit is in `server.py`.
- **No secrets in the repo:** keys live in `.env` (gitignored); `.env.example` has blanks only.
- **Simulated data labeled:** in every data file and in the UI.
- **Test set and accuracy:** `python eval/eval_ai.py` (13 notices + 10 incident reports).
- **Prototype disclaimer:** a banner at the top of the app.

## AI providers (with automatic backup)
1. **OpenRouter** (hackathon credits). Default model: `anthropic/claude-sonnet-5`, which you can change with `OPENROUTER_MODEL`.
2. **Gemini**: used automatically if OpenRouter fails or the credits run out (the app labels the answer "backup").
3. **Neither works:** every notice is marked NEEDS HUMAN REVIEW, which means flights HOLD and incidents HOLD. The app never guesses.

## Run it
```bash
cp .env.example .env                     # paste your OpenRouter key (and a free Gemini key as backup)
pip install -r requirements.txt          # only needed for the Gemini backup
python backend/server.py                 # http://localhost:8080 (also works with no keys: demo cache)
python -m unittest discover tests        # 16 safety + logic tests, incl. backup and all-AI-down
python eval/eval_ai.py                   # accuracy table comparing Claude Sonnet vs Gemini
python backend/build_demo.py             # frontend/demo.html, offline backup (no Wi-Fi needed)
```

## Deploy to Google Cloud Run
```bash
gcloud run deploy skyguard --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1
```
Give the Cloud Run service account the **Vertex AI User** role. For OpenRouter on Cloud Run, store the key in Secret Manager: `--set-secrets OPENROUTER_API_KEY=openrouter-key:latest`.

## Before demo day
1. Swap `data/notams_live.json` for real Cape Canaveral launch notices (tfr.faa.gov / FAA NOTAM API) and add 10+ past ones to `notam_testset.json`.
2. Swap `data/weather_campus.json` for live KLAL weather (aviationweather.gov METAR API).
3. Confirm Astro's reserve, prep time and wind limit, and the drone unit's specs, with Florida Poly PD. These are marked ASSUMED in `data/campus.json`.
4. Run `eval/eval_ai.py` and put the model comparison table on a slide.
5. Stretch goals: Google Maps instead of OpenStreetMap, Firestore for the decision log.

## 3-minute demo script
1. **Hook (20s):** "Florida is the only place where air taxis share the sky with rockets, and our own campus police now fly an eVTOL."
2. **Corridor (60s):** show launch notice FDC 6/4471 and its source text, then point out SG102 is in CONFLICT while SG103 is CLEAR (same airspace, but it lands before the launch window). Approve the delay.
3. **Security (40s):** press Play, SG105 drifts and circles, a HIGH RISK alert fires within about 2 minutes, then press "Contact aircraft."
4. **Campus (50s):** Lake Parker kayaker shows Astro ❌ (needs 24 of its 20 battery minutes), so the drone goes. Then the "record that guy in room 214" report gets the supervisor-review flag.
5. **Safety (10s):** tick "Simulate data outage" and every flight goes to HOLD.
