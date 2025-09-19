import os
import psycopg2
from psycopg2 import errors
from dotenv import load_dotenv
from flask import Flask, request, redirect, url_for, render_template_string, flash

# Load environment variables
load_dotenv()
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

app = Flask(__name__)
app.secret_key = os.getenv("flask_secret", "dev-secret")  # set FLASK_SECRET in .env for production

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Customer Marks</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif;margin:2rem;max-width:800px}
    form{display:grid;gap:0.75rem;max-width:420px}
    label{font-weight:600}
    input{padding:.6rem .7rem;border:1px solid #ccc;border-radius:8px;width:100%}
    button{padding:.6rem .9rem;border:0;border-radius:8px;background:#111;color:white;cursor:pointer}
    table{border-collapse:collapse;width:100%;margin-top:2rem}
    th,td{border:1px solid #eee;padding:.6rem;text-align:left}
    th{background:#fafafa}
    .flash{padding:.6rem .8rem;background:#eef;border:1px solid #cdd;border-radius:8px;margin:.75rem 0}
    .error{background:#fee;border-color:#fcc}
  </style>
</head>
<body>
  <h1>Customer Marks</h1>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="flash {{ 'error' if category == 'error' else '' }}">{{ msg|safe }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <form method="post" action="{{ url_for('add') }}">
    <div>
      <label for="name">Name</label>
      <input id="name" name="name" placeholder="e.g., Abhishek" required>
    </div>
    <div>
      <label for="marks">Marks</label>
      <input id="marks" name="marks" type="number" inputmode="numeric" placeholder="e.g., 92" required>
    </div>
    <button type="submit">Save</button>
  </form>

  <h2>Recent Entries</h2>
  <table>
    <thead>
      <tr><th>ID</th><th>Created At</th><th>Name</th><th>Marks</th></tr>
    </thead>
    <tbody>
      {% for row in rows %}
      <tr>
        <td>{{ row.id }}</td>
        <td>{{ row.created_at }}</td>
        <td>{{ row.name }}</td>
        <td>{{ row.marks }}</td>
      </tr>
      {% endfor %}
      {% if not rows %}
      <tr><td colspan="4">No data yet — add your first record above.</td></tr>
      {% endif %}
    </tbody>
  </table>
</body>
</html>
"""

def get_conn():
    return psycopg2.connect(
        user=USER, password=PASSWORD, host=HOST, port=PORT, dbname=DBNAME
    )

def sync_identity_sequence():
    """Align the identity sequence of public."Customer".id to MAX(id)."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute('SELECT pg_get_serial_sequence(%s, %s)', ('public."Customer"', 'id'))
            seq_row = cur.fetchone()
            if not seq_row or not seq_row[0]:
                return  # No sequence found (shouldn't happen with IDENTITY)
            seq_name = seq_row[0]
            cur.execute('SELECT COALESCE(MAX(id), 0) FROM public."Customer"')
            max_id = cur.fetchone()[0]
            # setval sets "last_value"; next nextval returns max_id+1
            cur.execute('SELECT setval(%s, %s)', (seq_name, max_id))
            conn.commit()
    except Exception as e:
        # Non-fatal; log to console
        print("Sequence sync failed:", e)

@app.route("/", methods=["GET"])
def index():
    rows = []
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, created_at, "Name", marks
                FROM public."Customer"
                ORDER BY created_at DESC
                LIMIT 25
            """)
            for r in cur.fetchall():
                created_at = r[1]
                created_at_str = created_at.strftime("%Y-%m-%d %H:%M:%S %Z") if hasattr(created_at, "strftime") else str(created_at)
                rows.append({"id": r[0], "created_at": created_at_str, "name": r[2], "marks": r[3]})
    except Exception as e:
        flash(f"DB read error: {e}", "error")
    return render_template_string(HTML, rows=rows)

def insert_customer(name: str, marks: int, retry_on_dup=True):
    """
    Insert a row. If a duplicate key on the IDENTITY happens,
    sync the sequence and retry once.
    """
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO public."Customer"("Name", marks) VALUES (%s, %s)', (name, marks))
            conn.commit()
        return True, None
    except errors.UniqueViolation as e:
        # Duplicate key (likely the identity sequence is behind)
        if retry_on_dup:
            try:
                sync_identity_sequence()
                with get_conn() as conn, conn.cursor() as cur:
                    cur.execute('INSERT INTO public."Customer"("Name", marks) VALUES (%s, %s)', (name, marks))
                    conn.commit()
                return True, None
            except Exception as e2:
                return False, f"Insert failed after sequence sync: {e2}"
        return False, f"Insert failed: {e}"
    except Exception as e:
        return False, f"Insert error: {e}"

@app.route("/add", methods=["POST"])
def add():
    name = (request.form.get("name") or "").strip()
    marks_raw = (request.form.get("marks") or "").strip()

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("index"))
    try:
        marks = int(marks_raw)
    except ValueError:
        flash("Marks must be an integer.", "error")
        return redirect(url_for("index"))

    ok, err = insert_customer(name, marks)
    if ok:
        flash(f'Saved <strong>{name}</strong> with marks <strong>{marks}</strong>.')
    else:
        flash(err or "Unknown error", "error")

    return redirect(url_for("index"))

if __name__ == "__main__":
    # Preemptively align the sequence once on startup
    sync_identity_sequence()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
