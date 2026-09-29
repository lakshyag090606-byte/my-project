# SignaBridge Prototype
Two-way communication assistant for deaf patients and hospital staff. Flask + SQLite backend, plain HTML/CSS/JS frontend.
Communication-assist only: the clinician can confirm, query or override every interpretation.

```
SignaBridge_Prototype/
├── backend/   main.py, requirements.txt, sample_requests.json, .gitignore
├── frontend/  index.html, styles.css, app.js
├── README.md
└── .gitignore
```

## Run (Python 3.9+)
Terminal 1 – backend (http://localhost:5000):
```
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
Terminal 2 – frontend (http://localhost:5500):
```
cd frontend
python -m http.server 5500
```
Open http://localhost:5500 in two browser tabs: one on **Patient**, one on **Doctor**.

## Demo
1. Patient: pick CHEST + PAIN, expression "visible pain", Send (or press the Emergency button).
2. Doctor: see urgency, flags and live stats; Confirm / Ask to re-sign / Override; send a typed or quick reply.
3. Patient: avatar plays the sign glosses; patient taps Understood / Not understood / Repeat.

## API (examples in backend/sample_requests.json)
GET /health, /vocabulary, /templates, /doctor/inbox[?pending=1], /patient/response/latest, /stats
POST /patient/interpret, /patient/emergency, /doctor/review/<id>, /doctor/respond, /patient/confirm/<id>, /reset
(all under /api)

## Notes
Sign recognition is simulated by the sign picker (real version: MediaPipe + classifier). Urgency scoring is simple rules, not medical logic. The avatar is a gloss-card placeholder for a 3D avatar.
