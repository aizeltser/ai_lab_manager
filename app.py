import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "eln.db"
UPLOAD_DIR = APP_DIR / "uploads"

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "webp", "gif",
    "pdf",
    "csv", "tsv", "txt",
    "xlsx",
    "json",
    "zip"
}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

LAB_OPTIONS = [
    ("wet", "Wet Lab"),
    ("dry", "Dry Lab"),
]


def now_iso():
    tz = timezone(timedelta(hours=3))
    return datetime.now(tz).isoformat(timespec="seconds")


def pretty_dt(value):
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return value
    return dt.strftime("%d.%m.%Y %H:%M")


app.jinja_env.filters["pretty_dt"] = pretty_dt


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_storage():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                lab TEXT,
                setup_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS concept_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id INTEGER NOT NULL,
                step_order INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS concept_notes (
                concept_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (concept_id) REFERENCES concepts(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                setup_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS experiment_ai_prompts (
                experiment_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS run_ai_prompts (
                run_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                stored_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                mime TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS experiment_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL,
                stored_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                mime TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        """)

        cols = [r["name"] for r in db.execute("PRAGMA table_info(experiments)").fetchall()]
        if "lab" not in cols:
            db.execute("ALTER TABLE experiments ADD COLUMN lab TEXT")
        if "setup_json" not in cols:
            db.execute("ALTER TABLE experiments ADD COLUMN setup_json TEXT")

        run_cols = [r["name"] for r in db.execute("PRAGMA table_info(runs)").fetchall()]
        if "setup_json" not in run_cols:
            db.execute("ALTER TABLE runs ADD COLUMN setup_json TEXT")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def unique_store_name(original_filename):
    safe = secure_filename(original_filename) or "file"
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    if "." in safe:
        base, ext = safe.rsplit(".", 1)
        return f"{base}_{stamp}.{ext}"
    return f"{safe}_{stamp}"


def parse_setup(value):
    if not value:
        return None
    try:
        data = json.loads(value)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    cols = data.get("columns")
    rows = data.get("rows")
    if not isinstance(cols, list) or not isinstance(rows, list):
        return None
    return {"columns": cols, "rows": rows}


@app.before_request
def ensure_ready():
    init_storage()


@app.context_processor
def inject_sidebar():
    with get_db() as db:
        experiments = db.execute("""
            SELECT id, title, lab, created_at
            FROM experiments
            ORDER BY datetime(created_at) DESC, id DESC
        """).fetchall()
        concepts = db.execute("""
            SELECT id, title, updated_at
            FROM concepts
            ORDER BY datetime(updated_at) DESC, id DESC
        """).fetchall()

    experiments_by_lab = {"wet": [], "dry": [], "unassigned": []}
    for e in experiments:
        lab = (e["lab"] or "").strip().lower() or "unassigned"
        if lab not in experiments_by_lab:
            experiments_by_lab[lab] = []
        experiments_by_lab[lab].append(e)

    return {
        "experiments_by_lab": experiments_by_lab,
        "experiments_all": experiments,
        "concepts_sidebar": concepts,
    }


@app.route("/")
def index():
    with get_db() as db:
        experiments = db.execute("""
            SELECT *
            FROM experiments
            ORDER BY datetime(created_at) DESC, id DESC
        """).fetchall()
    return render_template("index.html", experiments=experiments)


@app.route("/concepts")
def concepts():
    with get_db() as db:
        items = db.execute("""
            SELECT id, title, author, created_at, updated_at
            FROM concepts
            ORDER BY datetime(updated_at) DESC, id DESC
        """).fetchall()
    return render_template("concepts.html", concepts=items)


@app.route("/concept/new", methods=["GET", "POST"])
def concept_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip()

        if not title:
            flash("Concept title is required.", "error")
            return render_template("concept_new.html", form_title=title, form_author=author)
        if not author:
            flash("Author is required.", "error")
            return render_template("concept_new.html", form_title=title, form_author=author)

        stamp = now_iso()
        with get_db() as db:
            cur = db.execute("""
                INSERT INTO concepts (title, author, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (title, author, stamp, stamp))
            concept_id = cur.lastrowid

        flash("Concept created.", "success")
        return redirect(url_for("concept_view", concept_id=concept_id))

    return render_template("concept_new.html")


@app.route("/concept/<int:concept_id>")
def concept_view(concept_id):
    with get_db() as db:
        concept = db.execute("""
            SELECT *
            FROM concepts
            WHERE id = ?
        """, (concept_id,)).fetchone()
        if not concept:
            abort(404)
        steps = db.execute("""
            SELECT *
            FROM concept_steps
            WHERE concept_id = ?
            ORDER BY step_order ASC, id ASC
        """, (concept_id,)).fetchall()
        notes = db.execute("""
            SELECT *
            FROM concept_notes
            WHERE concept_id = ?
        """, (concept_id,)).fetchone()
    return render_template("concept_view.html", concept=concept, steps=steps, notes=notes)


@app.post("/concept/<int:concept_id>/step/new")
def concept_step_new(concept_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Step text is required.", "error")
        return redirect(url_for("concept_view", concept_id=concept_id))

    with get_db() as db:
        exists = db.execute("SELECT id FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if not exists:
            abort(404)
        last = db.execute("""
            SELECT MAX(step_order) AS max_order
            FROM concept_steps
            WHERE concept_id = ?
        """, (concept_id,)).fetchone()["max_order"]
        next_order = (last or 0) + 1
        stamp = now_iso()
        db.execute("""
            INSERT INTO concept_steps (concept_id, step_order, text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (concept_id, next_order, text, stamp, stamp))
        db.execute("""
            UPDATE concepts
            SET updated_at = ?
            WHERE id = ?
        """, (stamp, concept_id))

    flash("Step added.", "success")
    return redirect(url_for("concept_view", concept_id=concept_id))


@app.post("/concept/<int:concept_id>/notes")
def concept_notes_save(concept_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Researcher Notes cannot be empty.", "error")
        return redirect(url_for("concept_view", concept_id=concept_id))

    with get_db() as db:
        exists = db.execute("SELECT id FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO concept_notes (concept_id, text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(concept_id) DO UPDATE SET
              text=excluded.text,
              updated_at=excluded.updated_at
        """, (concept_id, text, stamp))
    flash("Researcher Notes saved.", "success")
    return redirect(url_for("concept_view", concept_id=concept_id))


@app.post("/experiment/<int:experiment_id>/ai")
def experiment_ai_save(experiment_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Prompt cannot be empty.", "error")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))

    with get_db() as db:
        exists = db.execute("SELECT id FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO experiment_ai_prompts (experiment_id, text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(experiment_id) DO UPDATE SET
              text=excluded.text,
              updated_at=excluded.updated_at
        """, (experiment_id, text, stamp))
    flash("Prompt saved.", "success")
    return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))


@app.post("/run/<int:run_id>/ai")
def run_ai_save(run_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Prompt cannot be empty.", "error")
        return redirect(url_for("run_view", run_id=run_id))

    with get_db() as db:
        exists = db.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO run_ai_prompts (run_id, text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              text=excluded.text,
              updated_at=excluded.updated_at
        """, (run_id, text, stamp))
    flash("Prompt saved.", "success")
    return redirect(url_for("run_view", run_id=run_id))


@app.route("/experiment/new", methods=["GET", "POST"])
def experiment_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        lab = (request.form.get("lab") or "").strip().lower()
        files = request.files.getlist("files")
        setup_json = (request.form.get("setup_json") or "").strip()

        lab_values = {v for v, _ in LAB_OPTIONS}

        if not title:
            flash("The name of the experiment is required.", "error")
            return render_template(
                "experiment_new.html",
                form_title=title,
                form_description=description,
                form_lab=lab,
                lab_options=LAB_OPTIONS,
            )

        if lab not in lab_values:
            flash("Choose a lab group.", "error")
            return render_template(
                "experiment_new.html",
                form_title=title,
                form_description=description,
                form_lab=lab,
                lab_options=LAB_OPTIONS,
            )

        with get_db() as db:
            cur = db.execute("""
                INSERT INTO experiments (title, description, lab, setup_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (title, description, lab, setup_json, now_iso()))
            experiment_id = cur.lastrowid

            for f in files:
                if not f or not f.filename:
                    continue
                if not allowed_file(f.filename):
                    flash(f"File '{f.filename}' is missing: invalid extension.", "error")
                    continue

                stored = unique_store_name(f.filename)
                f.save(UPLOAD_DIR / stored)

                db.execute("""
                    INSERT INTO experiment_attachments (experiment_id, stored_name, original_name, mime, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (experiment_id, stored, f.filename, f.mimetype, now_iso()))

        flash("Your experiment is created.", "success")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))

    return render_template("experiment_new.html", lab_options=LAB_OPTIONS)


@app.route("/experiment/<int:experiment_id>")
def experiment(experiment_id):
    tab = request.args.get("tab", "overview")

    with get_db() as db:
        exp = db.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()
        if not exp:
            abort(404)
        setup = parse_setup(exp["setup_json"])

        experiment_attachments = db.execute("""
            SELECT *
            FROM experiment_attachments
            WHERE experiment_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
        """, (experiment_id,)).fetchall()
        ai_prompt = db.execute("""
            SELECT *
            FROM experiment_ai_prompts
            WHERE experiment_id = ?
        """, (experiment_id,)).fetchone()

        runs = db.execute("""
            SELECT r.*,
                   (SELECT COUNT(*) FROM attachments a WHERE a.run_id = r.id) AS attachments_count
            FROM runs r
            WHERE r.experiment_id = ?
            ORDER BY datetime(r.created_at) DESC, r.id DESC
        """, (experiment_id,)).fetchall()

        recent_attachments = db.execute("""
            SELECT a.*, r.title AS run_title
            FROM attachments a
            JOIN runs r ON r.id = a.run_id
            WHERE r.experiment_id = ?
            ORDER BY datetime(a.created_at) DESC, a.id DESC
            LIMIT 6
        """, (experiment_id,)).fetchall()

    return render_template(
        "experiment.html",
        experiment=exp,
        setup=setup,
        runs=runs,
        tab=tab,
        recent_attachments=recent_attachments,
        experiment_attachments=experiment_attachments,
        ai_prompt=ai_prompt,
    )


@app.route("/experiment/<int:experiment_id>/run/new", methods=["GET", "POST"])
def run_new(experiment_id):
    with get_db() as db:
        exp = db.execute(
            "SELECT * FROM experiments WHERE id = ?",
            (experiment_id,),
        ).fetchone()
    if not exp:
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        files = request.files.getlist("files")
        setup_json = (request.form.get("setup_json") or "").strip()

        if not title:
            flash("The name of the run is required.", "error")
            return render_template("run_new.html", experiment=exp, form_title=title, form_notes=notes)

        with get_db() as db:
            cur = db.execute("""
                INSERT INTO runs (experiment_id, title, notes, setup_json, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (experiment_id, title, notes, setup_json, now_iso()))
            run_id = cur.lastrowid

            for f in files:
                if not f or not f.filename:
                    continue
                if not allowed_file(f.filename):
                    flash(f"File '{f.filename}' is missing: invalid extension.", "error")
                    continue

                stored = unique_store_name(f.filename)
                f.save(UPLOAD_DIR / stored)

                db.execute("""
                    INSERT INTO attachments (run_id, stored_name, original_name, mime, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (run_id, stored, f.filename, f.mimetype, now_iso()))

        flash("Run is saved.", "success")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="results"))

    return render_template("run_new.html", experiment=exp)


@app.route("/run/<int:run_id>")
def run_view(run_id):
    with get_db() as db:
        run = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            abort(404)
        exp = db.execute("SELECT * FROM experiments WHERE id = ?", (run["experiment_id"],)).fetchone()
        if not exp:
            abort(404)
        setup = parse_setup(run["setup_json"])
        ai_prompt = db.execute("""
            SELECT *
            FROM run_ai_prompts
            WHERE run_id = ?
        """, (run_id,)).fetchone()
        attachments = db.execute("""
            SELECT *
            FROM attachments
            WHERE run_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
        """, (run_id,)).fetchall()

    return render_template(
        "run_view.html",
        experiment=exp,
        run=run,
        attachments=attachments,
        setup=setup,
        ai_prompt=ai_prompt,
    )


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


@app.route("/attachment/<int:attachment_id>/download")
def attachment_download(attachment_id):
    with get_db() as db:
        att = db.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not att:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR,
        att["stored_name"],
        as_attachment=True,
        download_name=att["original_name"],
    )


@app.route("/experiment/attachment/<int:attachment_id>/download")
def experiment_attachment_download(attachment_id):
    with get_db() as db:
        att = db.execute("SELECT * FROM experiment_attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not att:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR,
        att["stored_name"],
        as_attachment=True,
        download_name=att["original_name"],
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
