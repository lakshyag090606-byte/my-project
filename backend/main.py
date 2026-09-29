"""SignaBridge prototype backend (Flask + SQLite).
Communication-assistance only: no diagnosis, clinician always reviews/overrides."""
import json, re, sqlite3, os
from datetime import datetime
from flask import Flask, jsonify, request, g

DB = os.path.join(os.path.dirname(__file__), "signabridge.db")
app = Flask(__name__)

# ---- Constrained healthcare vocabulary (synopsis 5.3 / 5.7) ----
# sign -> (category, urgency weight, emoji)
VOCAB = {
    "PAIN": ("symptom", 2, "😣"), "FEVER": ("symptom", 1, "🤒"), "DIZZY": ("symptom", 1, "😵"),
    "VOMIT": ("symptom", 1, "🤢"), "BREATHING": ("symptom", 3, "😮‍💨"), "BLEEDING": ("symptom", 3, "🩸"),
    "CHEST": ("body", 2, "🫀"), "HEAD": ("body", 0, "🤕"), "STOMACH": ("body", 0, "🫃"),
    "ARM": ("body", 0, "💪"), "LEG": ("body", 0, "🦵"),
    "HELP": ("request", 3, "🆘"), "MEDICINE": ("request", 0, "💊"), "WATER": ("request", 0, "💧"),
    "ALLERGY": ("request", 1, "⚠️"), "YES": ("answer", 0, "👍"), "NO": ("answer", 0, "👎"),
}
AFFECT = {"calm": 0, "distressed": 1, "visible_pain": 2}
LEVELS = ["low", "medium", "high", "critical"]

# doctor word -> gloss (constrained response vocabulary)
GLOSS = {
    "pain": "PAIN", "where": "WHERE", "chest": "CHEST", "head": "HEAD", "stomach": "STOMACH",
    "medicine": "MEDICINE", "tablet": "MEDICINE", "take": "TAKE", "water": "WATER", "drink": "DRINK",
    "wait": "WAIT", "rest": "REST", "doctor": "DOCTOR", "come": "COME", "now": "NOW", "test": "TEST",
    "allergy": "ALLERGY", "allergic": "ALLERGY", "you": "YOU", "your": "YOU", "we": "WE",
    "help": "HELP", "ok": "OK", "okay": "OK", "yes": "YES", "no": "NO", "sign": "SIGN",
    "consent": "CONSENT", "understand": "UNDERSTAND", "how": "HOW", "long": "LONG", "fever": "FEVER",
}
STOP = {"a", "the", "is", "are", "to", "will", "please", "do", "does", "have", "has", "and", "of", "for", "i", "it", "this", "that", "can", "with", "any", "there", "be"}

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS patient_messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT, signs TEXT, affect TEXT, summary TEXT,
      urgency TEXT, flags TEXT, review_status TEXT DEFAULT 'pending', override_text TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS doctor_responses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, message_id INTEGER REFERENCES patient_messages(id),
      text TEXT, glosses TEXT, unmapped TEXT, patient_status TEXT DEFAULT 'sent', created_at TEXT);
    """); c.commit(); c.close()

@app.after_request
def cors(r):  # frontend runs on a different port
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return r

def err(msg, code=400): return jsonify(error=msg), code
now = lambda: datetime.now().isoformat(timespec="seconds")

# ---- Business logic: rule-based interpretation ----
def interpret(signs, affect):
    score = sum(VOCAB[s][1] for s in signs) + AFFECT[affect]
    body = [s for s in signs if VOCAB[s][0] == "body"]
    sym = [s for s in signs if VOCAB[s][0] == "symptom"]
    if "CHEST" in signs and "PAIN" in signs: score += 2   # combination rule
    level = LEVELS[0 if score <= 1 else 1 if score <= 3 else 2 if score <= 5 else 3]
    flags = []
    if level in ("high", "critical"): flags.append("Urgent term/affect: confirm with patient immediately")
    if "HELP" in signs: flags.append("Patient signed HELP")
    if not sym and signs not in (["YES"], ["NO"]): flags.append("No symptom recognised: ask patient to re-sign")
    summary = (f"Symptom: {', '.join(sym) or 'not recognised'}; location: {', '.join(body) or 'not stated'}; "
               f"affect: {affect.replace('_', ' ')}.")
    return summary, level, flags

def to_glosses(text):
    words = re.findall(r"[a-z']+", text.lower())
    g_, un = [], []
    for w in words:
        if w in GLOSS: g_.append(GLOSS[w])
        elif w not in STOP: un.append(w)
    return g_, un

def row(r):
    d = dict(r)
    for k in ("signs", "flags", "glosses", "unmapped"):
        if k in d and d[k]: d[k] = json.loads(d[k])
    return d

# ---- API ----
@app.get("/api/health")
def health(): return jsonify(status="ok")

@app.get("/api/vocabulary")
def vocab():
    return jsonify(signs=[{"gloss": k, "category": v[0], "emoji": v[2]} for k, v in VOCAB.items()],
                   affects=list(AFFECT), response_words=sorted(set(GLOSS)))

@app.post("/api/patient/interpret")
def patient_interpret():
    data = request.get_json(silent=True) or {}
    signs = data.get("signs"); affect = data.get("affect", "calm")
    if not isinstance(signs, list) or not signs: return err("Select at least one sign.")
    bad = [s for s in signs if s not in VOCAB]
    if bad: return err(f"Unknown signs: {bad}")
    if affect not in AFFECT: return err("affect must be calm, distressed or visible_pain.")
    summary, level, flags = interpret(signs, affect)
    cur = db().execute("INSERT INTO patient_messages(signs,affect,summary,urgency,flags,created_at) VALUES(?,?,?,?,?,?)",
                       (json.dumps(signs), affect, summary, level, json.dumps(flags), now()))
    db().commit()
    return jsonify(id=cur.lastrowid, summary=summary, urgency=level, flags=flags), 201

@app.get("/api/doctor/inbox")
def inbox():
    where = "WHERE id NOT IN (SELECT message_id FROM doctor_responses)" if request.args.get("pending") == "1" else ""
    # unanswered first, then most urgent, then newest
    rows = db().execute(f"""SELECT * FROM patient_messages {where} ORDER BY
        id IN (SELECT message_id FROM doctor_responses),
        CASE urgency WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, id DESC LIMIT 30""").fetchall()
    out = []
    for r in rows:
        m = row(r)
        resp = db().execute("SELECT * FROM doctor_responses WHERE message_id=? ORDER BY id DESC LIMIT 1", (m["id"],)).fetchone()
        m["response"] = row(resp) if resp else None
        out.append(m)
    return jsonify(out)

@app.post("/api/doctor/review/<int:mid>")
def review(mid):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in ("confirm", "query", "override"): return err("action must be confirm, query or override.")
    if action == "override" and not (data.get("override_text") or "").strip(): return err("override_text required.")
    r = db().execute("UPDATE patient_messages SET review_status=?, override_text=? WHERE id=?",
                     (action, data.get("override_text"), mid))
    db().commit()
    return jsonify(ok=True) if r.rowcount else err("Message not found.", 404)

@app.post("/api/doctor/respond")
def respond():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip(); mid = data.get("message_id")
    if not text: return err("Response text is empty.")
    if not db().execute("SELECT 1 FROM patient_messages WHERE id=?", (mid,)).fetchone(): return err("Message not found.", 404)
    glosses, unmapped = to_glosses(text)
    if not glosses: return err("No words in the response match the sign vocabulary. Rephrase using supported words.")
    cur = db().execute("INSERT INTO doctor_responses(message_id,text,glosses,unmapped,created_at) VALUES(?,?,?,?,?)",
                       (mid, text, json.dumps(glosses), json.dumps(unmapped), now()))
    db().commit()
    return jsonify(id=cur.lastrowid, glosses=glosses, unmapped=unmapped), 201

@app.get("/api/patient/response/latest")
def latest():
    r = db().execute("SELECT * FROM doctor_responses WHERE patient_status IN ('sent','repeat') ORDER BY id DESC LIMIT 1").fetchone()
    return jsonify(row(r) if r else None)

@app.post("/api/patient/confirm/<int:rid>")
def confirm(rid):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("understood", "not_understood", "repeat"): return err("Invalid status.")
    r = db().execute("UPDATE doctor_responses SET patient_status=? WHERE id=?", (status, rid)); db().commit()
    return jsonify(ok=True) if r.rowcount else err("Response not found.", 404)


# ---- Extra features: quick replies, emergency shortcut, stats, demo reset ----
TEMPLATES = ["Where is the pain?", "Please wait, the doctor will come now.", "Do you have any allergy?",
             "Do you have fever?", "Take this medicine with water.", "Please rest, we will help you.", "Do you understand?"]

@app.get("/api/templates")
def templates(): return jsonify(TEMPLATES)

@app.post("/api/patient/emergency")
def emergency():
    cur = db().execute("INSERT INTO patient_messages(signs,affect,summary,urgency,flags,created_at) VALUES(?,?,?,?,?,?)",
        (json.dumps(["HELP"]), "visible_pain", "EMERGENCY button pressed by patient. Attend immediately.", "critical",
         json.dumps(["Emergency shortcut: patient needs staff now"]), now()))
    db().commit()
    return jsonify(id=cur.lastrowid, urgency="critical"), 201

@app.get("/api/stats")
def stats():
    q = lambda sql: db().execute(sql).fetchone()[0]
    unanswered = "id NOT IN (SELECT message_id FROM doctor_responses)"
    pairs = db().execute("""SELECT m.created_at a, MIN(r.created_at) b FROM patient_messages m
                            JOIN doctor_responses r ON r.message_id=m.id GROUP BY m.id""").fetchall()
    secs = [(datetime.fromisoformat(x["b"]) - datetime.fromisoformat(x["a"])).total_seconds() for x in pairs]
    replies = q("SELECT COUNT(*) FROM doctor_responses")
    return jsonify(total=q("SELECT COUNT(*) FROM patient_messages"),
                   awaiting_reply=q(f"SELECT COUNT(*) FROM patient_messages WHERE {unanswered}"),
                   critical_open=q(f"SELECT COUNT(*) FROM patient_messages WHERE urgency='critical' AND {unanswered}"),
                   avg_reply_seconds=round(sum(secs) / len(secs), 1) if secs else None,
                   understood_rate=round(q("SELECT COUNT(*) FROM doctor_responses WHERE patient_status='understood'") / replies, 2) if replies else None)

@app.post("/api/reset")
def reset():
    db().executescript("DELETE FROM doctor_responses; DELETE FROM patient_messages;"); db().commit()
    return jsonify(ok=True)

@app.route("/api/<path:_>", methods=["OPTIONS"])
def opts(_): return "", 204

if __name__ == "__main__":
    init_db(); app.run(port=5000, debug=True)
