"""
WCU Smart Meal - Backend API (Flask + SQLite)
Termux ላይ Node.js ሳያስፈልግ ይሰራል - Python ብቻ በቂ ነው።

ማስጀመሪያ (Termux):
    pkg install python -y
    pip install flask flask-cors
    python app.py

ሰርቨሩ በ http://127.0.0.1:5000 ላይ ይነሳል።
ስልክዎ/ብራውዘር ላይ ለመክፈት: http://127.0.0.1:5000
(thelast_connected.html ከ app.py ጋር በአንድ ፎልደር ውስጥ ካስቀመጡ፣
ይህን URL ብቻ ገብተው ሙሉ app ይከፈትልዎታል።)
"""

import sqlite3
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS

DB_PATH = "wcu_meal.db"
ADMIN_PASSWORD = "admin123"  # <-- ይህን ይቀይሩ
FRONTEND_FILE = "thelast_connected.html"  # ከ app.py ጋር በአንድ ፎልደር ውስጥ ያስቀምጡ

app = Flask(__name__)
CORS(app)


# ---------- FRONTEND ----------

@app.route("/")
def serve_frontend():
    folder = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(os.path.join(folder, FRONTEND_FILE)):
        return (
            f"{FRONTEND_FILE} አልተገኘም። እባክዎ thelast_connected.html ን "
            f"ከ app.py ጋር በተመሳሳይ ፎልደር ውስጥ ያስቀምጡ።",
            404,
        )
    return send_from_directory(folder, FRONTEND_FILE)


# ---------- DATABASE ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            pin TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            joined TEXT NOT NULL,
            meal_breakfast INTEGER NOT NULL DEFAULT 0,
            meal_lunch INTEGER NOT NULL DEFAULT 0,
            meal_dinner INTEGER NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            meal TEXT NOT NULL,
            time TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meal_times (
            meal TEXT PRIMARY KEY,
            start TEXT NOT NULL,
            end TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ነባሪ የምግብ ሰዓት
    defaults = [
        ("breakfast", "07:00", "09:30"),
        ("lunch", "12:00", "14:30"),
        ("dinner", "18:00", "20:30"),
    ]
    for meal, start, end in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO meal_times (meal, start, end) VALUES (?,?,?)",
            (meal, start, end),
        )

    cur.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('waste_rate', '0')"
    )

    conn.commit()
    conn.close()


def student_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "department": row["department"],
        "status": row["status"],
        "joined": row["joined"],
        "meals": {
            "breakfast": bool(row["meal_breakfast"]),
            "lunch": bool(row["meal_lunch"]),
            "dinner": bool(row["meal_dinner"]),
        },
    }


# ---------- STUDENT: REGISTER / LOGIN ----------

@app.route("/api/student/login", methods=["POST"])
def student_login():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    student_id = (data.get("id") or "").strip()
    department = (data.get("department") or "").strip()
    pin = (data.get("pin") or "").strip()

    if not (name and student_id and department and pin):
        return jsonify({"ok": False, "message": "እባክዎ ሁሉንም መረጃ ያስገቡ።"}), 400

    if len(pin) != 4 or not pin.isdigit():
        return jsonify({"ok": False, "message": "PIN በትክክል 4 አሃዝ መሆን አለበት።"}), 400

    db = get_db()
    row = db.execute(
        "SELECT * FROM students WHERE id=?", (student_id,)
    ).fetchone()

    if row is None:
        joined = datetime.now().strftime("%Y-%m-%d")
        db.execute(
            """INSERT INTO students
               (id, name, department, pin, status, joined,
                meal_breakfast, meal_lunch, meal_dinner)
               VALUES (?,?,?,?, 'pending', ?, 0,0,0)""",
            (student_id, name, department, pin, joined),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM students WHERE id=?", (student_id,)
        ).fetchone()
        return jsonify({
            "ok": True,
            "isNew": True,
            "student": student_to_dict(row),
            "message": "ምዝገባዎ ተሳክቷል። Admin ማረጋገጫ ይጠብቁ።",
        })

    if row["pin"] != pin:
        return jsonify({"ok": False, "message": "የተሳሳተ PIN!"}), 401

    return jsonify({
        "ok": True,
        "isNew": False,
        "student": student_to_dict(row),
        "message": f"እንኳን ደህና መጡ {row['name']}!",
    })


# ---------- ADMIN LOGIN ----------

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True)
    password = data.get("password") or ""
    if password == ADMIN_PASSWORD:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "የተሳሳተ Admin password!"}), 401


# ---------- STUDENTS LIST / APPROVE / REJECT ----------

@app.route("/api/students", methods=["GET"])
def list_students():
    db = get_db()
    rows = db.execute("SELECT * FROM students").fetchall()
    return jsonify({"ok": True, "students": [student_to_dict(r) for r in rows]})


@app.route("/api/students/<student_id>/approve", methods=["POST"])
def approve_student(student_id):
    db = get_db()
    db.execute("UPDATE students SET status='approved' WHERE id=?", (student_id,))
    db.commit()
    row = db.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if row is None:
        return jsonify({"ok": False, "message": "ተማሪው አልተገኘም።"}), 404
    return jsonify({"ok": True, "student": student_to_dict(row)})


@app.route("/api/students/<student_id>/reject", methods=["POST"])
def reject_student(student_id):
    db = get_db()
    db.execute("UPDATE students SET status='rejected' WHERE id=?", (student_id,))
    db.commit()
    row = db.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if row is None:
        return jsonify({"ok": False, "message": "ተማሪው አልተገኘም።"}), 404
    return jsonify({"ok": True, "student": student_to_dict(row)})


# ---------- MEAL TIMES ----------

@app.route("/api/mealtimes", methods=["GET"])
def get_meal_times():
    db = get_db()
    rows = db.execute("SELECT * FROM meal_times").fetchall()
    result = {r["meal"]: {"start": r["start"], "end": r["end"]} for r in rows}
    return jsonify({"ok": True, "mealTimes": result})


@app.route("/api/mealtimes", methods=["POST"])
def set_meal_times():
    data = request.get_json(force=True)
    db = get_db()
    for meal in ("breakfast", "lunch", "dinner"):
        if meal in data:
            db.execute(
                "UPDATE meal_times SET start=?, end=? WHERE meal=?",
                (data[meal]["start"], data[meal]["end"], meal),
            )
    db.commit()
    return jsonify({"ok": True, "message": "የምግብ ሰዓት ተቀምጧል!"})


def is_meal_time_allowed(db, meal):
    row = db.execute("SELECT * FROM meal_times WHERE meal=?", (meal,)).fetchone()
    if row is None:
        return True
    now = datetime.now()
    sh, sm = map(int, row["start"].split(":"))
    eh, em = map(int, row["end"].split(":"))
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


# ---------- QR SCAN ----------

MEAL_NAMES = {"breakfast": "🌅 ቁርስ", "lunch": "☀️ ምሳ", "dinner": "🌙 እራት"}

@app.route("/api/scan", methods=["POST"])
def scan_qr():
    data = request.get_json(force=True)
    qr_raw = data.get("qrData")
    meal_type = data.get("mealType")

    if meal_type not in MEAL_NAMES:
        return jsonify({"ok": False, "message": "ልክ ያልሆነ የምግብ አይነት።"}), 400

    try:
        qr_payload = json.loads(qr_raw) if isinstance(qr_raw, str) else qr_raw
    except (json.JSONDecodeError, TypeError):
        return jsonify({"ok": False, "message": "የQR ኮዱ ትክክል አይደለም።"}), 400

    if qr_payload.get("verification") != "WCU-SMART-MEAL" or qr_payload.get("approved") is not True:
        return jsonify({"ok": False, "message": "ይህ QR የWCU Smart Meal QR አይደለም።"}), 400

    db = get_db()
    student = db.execute(
        "SELECT * FROM students WHERE id=?", (qr_payload.get("studentId"),)
    ).fetchone()

    if student is None:
        return jsonify({"ok": False, "message": "ተማሪው በስርዓቱ አልተገኘም።"}), 404

    if student["status"] != "approved":
        return jsonify({"ok": False, "message": "ተማሪው በAdmin አልፀደቀም።"}), 403

    if not is_meal_time_allowed(db, meal_type):
        row = db.execute("SELECT * FROM meal_times WHERE meal=?", (meal_type,)).fetchone()
        return jsonify({
            "ok": False,
            "message": f"የ{MEAL_NAMES[meal_type]} ሰዓት አይደለም። የተፈቀደው ሰዓት: {row['start']} - {row['end']}",
        }), 403

    col = f"meal_{meal_type}"
    if student[col]:
        return jsonify({
            "ok": False,
            "message": "ምግቡ ቀድሞ ተወስዷል",
            "student": {"name": student["name"]},
            "meal": MEAL_NAMES[meal_type],
        }), 409

    db.execute(f"UPDATE students SET {col}=1 WHERE id=?", (student["id"],))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO scan_logs (student_id, name, meal, time) VALUES (?,?,?,?)",
        (student["id"], student["name"], meal_type, now_str),
    )
    db.commit()

    return jsonify({
        "ok": True,
        "message": "ምግብ ተፈቅዷል!",
        "student": {"id": student["id"], "name": student["name"]},
        "meal": MEAL_NAMES[meal_type],
        "time": now_str,
    })


# ---------- MEALS / STATS ----------

@app.route("/api/meals", methods=["GET"])
def get_meals():
    db = get_db()
    counts = {}
    for meal in ("breakfast", "lunch", "dinner"):
        col = f"meal_{meal}"
        n = db.execute(f"SELECT COUNT(*) c FROM students WHERE {col}=1").fetchone()["c"]
        counts[meal] = n

    total_scans = db.execute("SELECT COUNT(*) c FROM scan_logs").fetchone()["c"]
    total_students = db.execute("SELECT COUNT(*) c FROM students").fetchone()["c"]
    pending = db.execute(
        "SELECT COUNT(*) c FROM students WHERE status='pending'"
    ).fetchone()["c"]

    return jsonify({
        "ok": True,
        "meals": counts,
        "totalScans": total_scans,
        "totalStudents": total_students,
        "pendingStudents": pending,
    })


# ---------- WASTE ----------

@app.route("/api/waste", methods=["POST"])
def calculate_waste():
    data = request.get_json(force=True)
    prepared = float(data.get("prepared", 0))
    wasted = float(data.get("wasted", 0))

    if prepared <= 0 or wasted < 0 or wasted > prepared:
        return jsonify({"ok": False, "message": "እባክዎ ትክክለኛ ቁጥር ያስገቡ።"}), 400

    consumed = prepared - wasted
    percentage = round((wasted / prepared) * 100, 1)

    db = get_db()
    db.execute(
        "UPDATE settings SET value=? WHERE key='waste_rate'", (str(percentage),)
    )
    db.commit()

    return jsonify({
        "ok": True,
        "prepared": prepared,
        "consumed": consumed,
        "wasted": wasted,
        "percentage": percentage,
    })


# ---------- RESET ----------

@app.route("/api/reset", methods=["POST"])
def reset_report():
    db = get_db()
    db.execute(
        "UPDATE students SET meal_breakfast=0, meal_lunch=0, meal_dinner=0"
    )
    db.execute("DELETE FROM scan_logs")
    db.commit()
    return jsonify({"ok": True, "message": "ሪፖርቱ ዳግም ተጀምሯል!"})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)


