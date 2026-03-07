import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import re

from dotenv import load_dotenv

load_dotenv()

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "webp", "gif",
    "pdf",
    "csv", "tsv", "txt",
    "xlsx",
    "json",
    "zip"
}

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://antines:qweasd123@localhost:5432/eln_db"
)

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=2,
    max_size=10,
    kwargs={"row_factory": dict_row},
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

LAB_OPTIONS = [
    ("wet", "Wet Lab"),
    ("dry", "Dry Lab"),
]

TAG_COLORS = ["red", "amber", "green", "blue", "purple", "pink", "gray", "teal"]

PAGE_TEMPLATES = {
    "wet_lab": {
        "label": "Wet Lab Protocol",
        "data": {
            "time": 0,
            "version": "2.28.0",
            "blocks": [
                {"type": "header", "data": {"text": "Objective", "level": 2}},
                {"type": "paragraph", "data": {"text": "Describe the goal of this experiment."}},
                {"type": "header", "data": {"text": "Materials", "level": 2}},
                {"type": "list", "data": {"style": "unordered", "items": ["Reagent A", "Reagent B", "Equipment"]}},
                {"type": "header", "data": {"text": "Protocol Steps", "level": 2}},
                {"type": "list", "data": {"style": "ordered", "items": ["Step 1: Prepare samples", "Step 2: Run assay", "Step 3: Measure results"]}},
                {"type": "header", "data": {"text": "Setup / Conditions", "level": 2}},
                {"type": "table", "data": {"withHeadings": True, "content": [["Parameter", "Value", "Unit"], ["Temperature", "", "°C"], ["Duration", "", "min"], ["Concentration", "", "mM"]]}},
                {"type": "header", "data": {"text": "Results", "level": 2}},
                {"type": "paragraph", "data": {"text": "Record observations and measurements here."}},
                {"type": "header", "data": {"text": "Conclusions", "level": 2}},
                {"type": "paragraph", "data": {"text": "Summarize findings and next steps."}},
            ],
        },
    },
    "pipeline": {
        "label": "Bioinformatics Pipeline",
        "data": {
            "time": 0,
            "version": "2.28.0",
            "blocks": [
                {"type": "header", "data": {"text": "Pipeline Overview", "level": 2}},
                {"type": "paragraph", "data": {"text": "Brief description of the analysis pipeline."}},
                {"type": "header", "data": {"text": "Input Data", "level": 2}},
                {"type": "table", "data": {"withHeadings": True, "content": [["Dataset", "Source", "Format", "Size"], ["", "", "", ""]]}},
                {"type": "header", "data": {"text": "Tools & Versions", "level": 2}},
                {"type": "list", "data": {"style": "unordered", "items": ["Tool v1.0", "Tool v2.0"]}},
                {"type": "header", "data": {"text": "Pipeline Steps", "level": 2}},
                {"type": "list", "data": {"style": "ordered", "items": ["Quality control", "Alignment / Mapping", "Variant calling / Analysis", "Annotation", "Visualization"]}},
                {"type": "header", "data": {"text": "Parameters", "level": 2}},
                {"type": "code", "data": {"code": "# Key parameters\nparam1 = value\nparam2 = value"}},
                {"type": "header", "data": {"text": "Output & Results", "level": 2}},
                {"type": "paragraph", "data": {"text": "Describe output files and key findings."}},
            ],
        },
    },
    "meeting": {
        "label": "Meeting Notes",
        "data": {
            "time": 0,
            "version": "2.28.0",
            "blocks": [
                {"type": "header", "data": {"text": "Meeting Details", "level": 2}},
                {"type": "table", "data": {"withHeadings": False, "content": [["Date", ""], ["Attendees", ""], ["Location", ""]]}},
                {"type": "header", "data": {"text": "Agenda", "level": 2}},
                {"type": "list", "data": {"style": "ordered", "items": ["Topic 1", "Topic 2", "Topic 3"]}},
                {"type": "header", "data": {"text": "Discussion Notes", "level": 2}},
                {"type": "paragraph", "data": {"text": "Key points discussed..."}},
                {"type": "header", "data": {"text": "Action Items", "level": 2}},
                {"type": "checklist", "data": {"items": [{"text": "Action item 1 — Owner", "checked": False}, {"text": "Action item 2 — Owner", "checked": False}]}},
                {"type": "header", "data": {"text": "Next Steps", "level": 2}},
                {"type": "paragraph", "data": {"text": "Follow-up actions and next meeting date."}},
            ],
        },
    },
}


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


@contextmanager
def get_db():
    with pool.connection() as conn:
        yield conn


def init_storage():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                lab TEXT,
                setup_json TEXT,
                content_json TEXT,
                parent_type TEXT,
                parent_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                content_json TEXT,
                parent_type TEXT,
                parent_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS concept_steps (
                id SERIAL PRIMARY KEY,
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
                concept_id INTEGER PRIMARY KEY REFERENCES concepts(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id SERIAL PRIMARY KEY,
                experiment_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                setup_json TEXT,
                content_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS experiment_ai_prompts (
                experiment_id INTEGER PRIMARY KEY REFERENCES experiments(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS run_ai_prompts (
                run_id INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                id SERIAL PRIMARY KEY,
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
                id SERIAL PRIMARY KEY,
                experiment_id INTEGER NOT NULL,
                stored_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                mime TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id SERIAL PRIMARY KEY,
                stored_name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                mime TEXT,
                size_bytes INTEGER,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                created_at TEXT NOT NULL
            )
        """)

        # --- Activity log ---
        db.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id SERIAL PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                entity_title TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # --- Tags ---
        db.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name CITEXT NOT NULL UNIQUE,
                color TEXT NOT NULL DEFAULT 'blue'
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS entity_tags (
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (entity_type, entity_id, tag_id),
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            )
        """)


def _make_editor_json(blocks):
    return json.dumps({
        "time": int(time.time() * 1000),
        "blocks": blocks,
        "version": "2.28.0",
    })


def migrate_legacy_content():
    with get_db() as db:
        # Migrate concepts (steps + notes -> content_json)
        concepts = db.execute(
            "SELECT id FROM concepts WHERE content_json IS NULL"
        ).fetchall()
        for c in concepts:
            cid = c["id"]
            blocks = []
            notes = db.execute(
                "SELECT text FROM concept_notes WHERE concept_id = %s", (cid,)
            ).fetchone()
            if notes and notes["text"]:
                blocks.append({"type": "paragraph", "data": {"text": notes["text"]}})
            steps = db.execute(
                "SELECT text FROM concept_steps WHERE concept_id = %s ORDER BY step_order",
                (cid,),
            ).fetchall()
            if steps:
                blocks.append({"type": "header", "data": {"text": "Steps", "level": 2}})
                blocks.append({
                    "type": "list",
                    "data": {"style": "ordered", "items": [s["text"] for s in steps]},
                })
            if blocks:
                db.execute(
                    "UPDATE concepts SET content_json = %s WHERE id = %s",
                    (_make_editor_json(blocks), cid),
                )

        # Migrate experiments (description + setup_json -> content_json)
        experiments = db.execute(
            "SELECT id, description, setup_json FROM experiments WHERE content_json IS NULL"
        ).fetchall()
        for e in experiments:
            blocks = []
            if e["description"]:
                blocks.append({"type": "paragraph", "data": {"text": e["description"]}})
            setup = parse_setup(e["setup_json"])
            if setup:
                blocks.append({"type": "header", "data": {"text": "Physical Experiment Setup", "level": 2}})
                header = ["Parameter"] + setup["columns"]
                rows = [[r["label"]] + r["values"] for r in setup["rows"]]
                blocks.append({
                    "type": "table",
                    "data": {"withHeadings": True, "content": [header] + rows},
                })
            if blocks:
                db.execute(
                    "UPDATE experiments SET content_json = %s WHERE id = %s",
                    (_make_editor_json(blocks), e["id"]),
                )

        # Migrate runs (notes + setup_json -> content_json)
        runs = db.execute(
            "SELECT id, notes, setup_json FROM runs WHERE content_json IS NULL"
        ).fetchall()
        for r in runs:
            blocks = []
            if r["notes"]:
                blocks.append({"type": "paragraph", "data": {"text": r["notes"]}})
            setup = parse_setup(r["setup_json"])
            if setup:
                blocks.append({"type": "header", "data": {"text": "Physical Experiment Setup", "level": 2}})
                header = ["Parameter"] + setup["columns"]
                rows = [[row["label"]] + row["values"] for row in setup["rows"]]
                blocks.append({
                    "type": "table",
                    "data": {"withHeadings": True, "content": [header] + rows},
                })
            if blocks:
                db.execute(
                    "UPDATE runs SET content_json = %s WHERE id = %s",
                    (_make_editor_json(blocks), r["id"]),
                )


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


def sanitize_html(text):
    if not text:
        return ""
    text = re.sub(r"<\s*(script|iframe|object|embed|form)[^>]*>.*?</\s*\1\s*>", "", text, flags=re.I | re.S)
    text = re.sub(r"<\s*(script|iframe|object|embed|form)[^>]*/?>", "", text, flags=re.I)
    text = re.sub(r"\s+on\w+\s*=\s*[\"'][^\"']*[\"']", "", text, flags=re.I)
    text = re.sub(r"\s+on\w+\s*=\s*\S+", "", text, flags=re.I)
    return text


app.jinja_env.filters["sanitize"] = sanitize_html


def link_media(entity_type, entity_id, content_json_str):
    urls = re.findall(r'/uploads/([^\s"\']+)', content_json_str or "")
    with get_db() as db:
        for stored_name in urls:
            db.execute("""
                UPDATE media SET entity_type = %s, entity_id = %s
                WHERE stored_name = %s AND (entity_id IS NULL OR entity_id = %s)
            """, (entity_type, entity_id, stored_name, entity_id))


def parse_content_json(value):
    if not value:
        return None
    try:
        data = json.loads(value)
    except Exception:
        return None
    if isinstance(data, dict) and "blocks" in data:
        return data
    return None


def lab_label(code):
    for val, lbl in LAB_OPTIONS:
        if val == code:
            return lbl
    return "Unassigned"


def make_breadcrumbs(*crumbs):
    return list(crumbs)


def log_activity(entity_type, entity_id, entity_title, action):
    with get_db() as db:
        db.execute("""
            INSERT INTO activity_log (entity_type, entity_id, entity_title, action, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (entity_type, entity_id, entity_title, action, now_iso()))


def get_entity_tags(db, entity_type, entity_id):
    return db.execute("""
        SELECT t.* FROM tags t
        JOIN entity_tags et ON et.tag_id = t.id
        WHERE et.entity_type = %s AND et.entity_id = %s
        ORDER BY t.name
    """, (entity_type, entity_id)).fetchall()


def get_all_tags(db):
    return db.execute("SELECT * FROM tags ORDER BY name").fetchall()


def build_sidebar_tree(experiments, concepts):
    nodes = {}
    for e in experiments:
        nodes[("experiment", e["id"])] = {
            "type": "experiment",
            "id": e["id"],
            "title": e["title"],
            "lab": e["lab"],
            "parent_type": e["parent_type"],
            "parent_id": e["parent_id"],
            "children": [],
        }
    for c in concepts:
        nodes[("concept", c["id"])] = {
            "type": "concept",
            "id": c["id"],
            "title": c["title"],
            "lab": None,
            "parent_type": c["parent_type"],
            "parent_id": c["parent_id"],
            "children": [],
        }

    roots = []
    for key, node in nodes.items():
        pt = node["parent_type"]
        pid = node["parent_id"]
        if pt and pid and (pt, pid) in nodes:
            nodes[(pt, pid)]["children"].append(node)
        else:
            roots.append(node)

    return roots


def get_ancestor_chain(db, entity_type, entity_id, max_depth=20):
    chain = []
    visited = set()
    et, eid = entity_type, entity_id
    for _ in range(max_depth):
        if not et or not eid or (et, eid) in visited:
            break
        visited.add((et, eid))
        if et == "experiment":
            row = db.execute("SELECT id, title, parent_type, parent_id FROM experiments WHERE id = %s", (eid,)).fetchone()
            if row:
                chain.append(("experiment", row["id"], row["title"]))
                et, eid = row["parent_type"], row["parent_id"]
            else:
                break
        elif et == "concept":
            row = db.execute("SELECT id, title, parent_type, parent_id FROM concepts WHERE id = %s", (eid,)).fetchone()
            if row:
                chain.append(("concept", row["id"], row["title"]))
                et, eid = row["parent_type"], row["parent_id"]
            else:
                break
        else:
            break
    chain.reverse()
    return chain


def get_parent_options(db, exclude_type=None, exclude_id=None):
    experiments = db.execute("SELECT id, title FROM experiments ORDER BY title").fetchall()
    concepts = db.execute("SELECT id, title FROM concepts ORDER BY title").fetchall()
    options = []
    for e in experiments:
        if exclude_type == "experiment" and exclude_id == e["id"]:
            continue
        options.append(("experiment", e["id"], e["title"]))
    for c in concepts:
        if exclude_type == "concept" and exclude_id == c["id"]:
            continue
        options.append(("concept", c["id"], c["title"]))
    return options


# Run init_storage() once at startup instead of per-request
with app.app_context():
    init_storage()
    migrate_legacy_content()


@app.context_processor
def inject_sidebar():
    with get_db() as db:
        experiments = db.execute("""
            SELECT id, title, lab, parent_type, parent_id, created_at
            FROM experiments
            ORDER BY created_at DESC, id DESC
        """).fetchall()
        concepts = db.execute("""
            SELECT id, title, parent_type, parent_id, updated_at
            FROM concepts
            ORDER BY updated_at DESC, id DESC
        """).fetchall()
        tags_all = get_all_tags(db)

    sidebar_tree = build_sidebar_tree(experiments, concepts)

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
        "sidebar_tree": sidebar_tree,
        "tags_all": tags_all,
        "lab_label": lab_label,
    }


@app.route("/")
def index():
    tag_filter = request.args.get("tag", type=int)
    with get_db() as db:
        if tag_filter:
            experiments = db.execute("""
                SELECT e.* FROM experiments e
                JOIN entity_tags et ON et.entity_type = 'experiment' AND et.entity_id = e.id
                WHERE et.tag_id = %s
                ORDER BY e.created_at DESC, e.id DESC
            """, (tag_filter,)).fetchall()
        else:
            experiments = db.execute("""
                SELECT *
                FROM experiments
                ORDER BY created_at DESC, id DESC
            """).fetchall()
        activity = db.execute("""
            SELECT * FROM activity_log
            ORDER BY created_at DESC, id DESC
            LIMIT 20
        """).fetchall()
    return render_template("index.html", experiments=experiments, activity=activity, tag_filter=tag_filter)


@app.route("/concepts")
def concepts():
    tag_filter = request.args.get("tag", type=int)
    with get_db() as db:
        if tag_filter:
            items = db.execute("""
                SELECT c.id, c.title, c.author, c.created_at, c.updated_at
                FROM concepts c
                JOIN entity_tags et ON et.entity_type = 'concept' AND et.entity_id = c.id
                WHERE et.tag_id = %s
                ORDER BY c.updated_at DESC, c.id DESC
            """, (tag_filter,)).fetchall()
        else:
            items = db.execute("""
                SELECT id, title, author, created_at, updated_at
                FROM concepts
                ORDER BY updated_at DESC, id DESC
            """).fetchall()
    return render_template("concepts.html", concepts=items, tag_filter=tag_filter)


@app.route("/concept/new", methods=["GET", "POST"])
def concept_new():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip()
        content_json = (request.form.get("content_json") or "").strip() or None
        parent_raw = (request.form.get("parent") or "").strip()
        parent_type = parent_id = None
        if parent_raw and ":" in parent_raw:
            pt, pid = parent_raw.split(":", 1)
            if pt in ("experiment", "concept") and pid.isdigit():
                parent_type, parent_id = pt, int(pid)

        if not title:
            flash("Concept title is required.", "error")
            with get_db() as db:
                parent_options = get_parent_options(db)
            return render_template("concept_new.html", form_title=title, form_author=author, parent_options=parent_options, page_templates=PAGE_TEMPLATES)
        if not author:
            flash("Author is required.", "error")
            with get_db() as db:
                parent_options = get_parent_options(db)
            return render_template("concept_new.html", form_title=title, form_author=author, parent_options=parent_options, page_templates=PAGE_TEMPLATES)

        stamp = now_iso()
        with get_db() as db:
            cur = db.execute("""
                INSERT INTO concepts (title, author, content_json, parent_type, parent_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (title, author, content_json, parent_type, parent_id, stamp, stamp))
            concept_id = cur.fetchone()["id"]

        if content_json:
            link_media("concept", concept_id, content_json)

        log_activity("concept", concept_id, title, "created")
        flash("Concept created.", "success")
        return redirect(url_for("concept_view", concept_id=concept_id))

    template_key = request.args.get("template")
    template_data = None
    if template_key and template_key in PAGE_TEMPLATES:
        template_data = json.dumps(PAGE_TEMPLATES[template_key]["data"])

    with get_db() as db:
        parent_options = get_parent_options(db)

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), ("Concepts", url_for("concepts")), ("New", None))
    return render_template("concept_new.html", parent_options=parent_options, page_templates=PAGE_TEMPLATES, template_data=template_data, breadcrumbs=breadcrumbs)


@app.route("/concept/<int:concept_id>")
def concept_view(concept_id):
    with get_db() as db:
        concept = db.execute("""
            SELECT *
            FROM concepts
            WHERE id = %s
        """, (concept_id,)).fetchone()
        if not concept:
            abort(404)

        content = parse_content_json(concept["content_json"])

        steps = db.execute("""
            SELECT *
            FROM concept_steps
            WHERE concept_id = %s
            ORDER BY step_order ASC, id ASC
        """, (concept_id,)).fetchall()
        notes = db.execute("""
            SELECT *
            FROM concept_notes
            WHERE concept_id = %s
        """, (concept_id,)).fetchone()

        entity_tags = get_entity_tags(db, "concept", concept_id)
        all_tags = get_all_tags(db)
        ancestors = get_ancestor_chain(db, concept["parent_type"], concept["parent_id"])

    crumbs = [("Home", url_for("index")), ("Concepts", url_for("concepts"))]
    for atype, aid, atitle in ancestors:
        if atype == "experiment":
            crumbs.append((atitle, url_for("experiment", experiment_id=aid, tab="overview")))
        else:
            crumbs.append((atitle, url_for("concept_view", concept_id=aid)))
    crumbs.append((concept["title"], None))
    breadcrumbs = make_breadcrumbs(*crumbs)

    return render_template("concept_view.html", concept=concept, content=content, steps=steps, notes=notes, entity_tags=entity_tags, all_tags=all_tags, breadcrumbs=breadcrumbs, tag_colors=TAG_COLORS)


@app.post("/concept/<int:concept_id>/step/new")
def concept_step_new(concept_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Step text is required.", "error")
        return redirect(url_for("concept_view", concept_id=concept_id))

    with get_db() as db:
        exists = db.execute("SELECT id FROM concepts WHERE id = %s", (concept_id,)).fetchone()
        if not exists:
            abort(404)
        last = db.execute("""
            SELECT MAX(step_order) AS max_order
            FROM concept_steps
            WHERE concept_id = %s
        """, (concept_id,)).fetchone()["max_order"]
        next_order = (last or 0) + 1
        stamp = now_iso()
        db.execute("""
            INSERT INTO concept_steps (concept_id, step_order, text, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (concept_id, next_order, text, stamp, stamp))
        db.execute("""
            UPDATE concepts
            SET updated_at = %s
            WHERE id = %s
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
        exists = db.execute("SELECT id FROM concepts WHERE id = %s", (concept_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO concept_notes (concept_id, text, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT(concept_id) DO UPDATE SET
              text=excluded.text,
              updated_at=excluded.updated_at
        """, (concept_id, text, stamp))
    flash("Researcher Notes saved.", "success")
    return redirect(url_for("concept_view", concept_id=concept_id))


@app.route("/concept/<int:concept_id>/edit", methods=["GET", "POST"])
def concept_edit(concept_id):
    with get_db() as db:
        concept = db.execute("SELECT * FROM concepts WHERE id = %s", (concept_id,)).fetchone()
        if not concept:
            abort(404)

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            content_json = (request.form.get("content_json") or "").strip() or None
            parent_raw = (request.form.get("parent") or "").strip()
            parent_type = parent_id = None
            if parent_raw and ":" in parent_raw:
                pt, pid = parent_raw.split(":", 1)
                if pt in ("experiment", "concept") and pid.isdigit():
                    parent_type, parent_id = pt, int(pid)

            if not title:
                flash("Title is required.", "error")
                parent_options = get_parent_options(db, "concept", concept_id)
                return render_template("concept_edit.html", concept=concept, parent_options=parent_options)

            stamp = now_iso()
            db.execute("""
                UPDATE concepts SET title = %s, content_json = %s, parent_type = %s, parent_id = %s, updated_at = %s
                WHERE id = %s
            """, (title, content_json, parent_type, parent_id, stamp, concept_id))

            if content_json:
                link_media("concept", concept_id, content_json)

            log_activity("concept", concept_id, title, "edited")
            flash("Concept updated.", "success")
            return redirect(url_for("concept_view", concept_id=concept_id))

        parent_options = get_parent_options(db, "concept", concept_id)

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), ("Concepts", url_for("concepts")), (concept["title"], url_for("concept_view", concept_id=concept_id)), ("Edit", None))
    return render_template("concept_edit.html", concept=concept, parent_options=parent_options, breadcrumbs=breadcrumbs)


@app.post("/concept/<int:concept_id>/delete")
def concept_delete(concept_id):
    with get_db() as db:
        row = db.execute("SELECT id, title FROM concepts WHERE id = %s", (concept_id,)).fetchone()
        if not row:
            abort(404)
        db.execute("DELETE FROM entity_tags WHERE entity_type = 'concept' AND entity_id = %s", (concept_id,))
        db.execute("DELETE FROM concepts WHERE id = %s", (concept_id,))
    log_activity("concept", concept_id, row["title"], "deleted")
    flash("Concept deleted.", "success")
    return redirect(url_for("concepts"))


@app.post("/experiment/<int:experiment_id>/delete")
def experiment_delete(experiment_id):
    with get_db() as db:
        row = db.execute("SELECT id, title FROM experiments WHERE id = %s", (experiment_id,)).fetchone()
        if not row:
            abort(404)
        db.execute("DELETE FROM entity_tags WHERE entity_type = 'experiment' AND entity_id = %s", (experiment_id,))
        db.execute("DELETE FROM experiments WHERE id = %s", (experiment_id,))
    log_activity("experiment", experiment_id, row["title"], "deleted")
    flash("Experiment deleted.", "success")
    return redirect(url_for("index"))


@app.post("/run/<int:run_id>/delete")
def run_delete(run_id):
    with get_db() as db:
        run = db.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
        if not run:
            abort(404)
        experiment_id = run["experiment_id"]
        db.execute("DELETE FROM entity_tags WHERE entity_type = 'run' AND entity_id = %s", (run_id,))
        db.execute("DELETE FROM runs WHERE id = %s", (run_id,))
    log_activity("run", run_id, run["title"], "deleted")
    flash("Run deleted.", "success")
    return redirect(url_for("experiment", experiment_id=experiment_id, tab="results"))


@app.post("/experiment/<int:experiment_id>/ai")
def experiment_ai_save(experiment_id):
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Prompt cannot be empty.", "error")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))

    with get_db() as db:
        exists = db.execute("SELECT id FROM experiments WHERE id = %s", (experiment_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO experiment_ai_prompts (experiment_id, text, updated_at)
            VALUES (%s, %s, %s)
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
        exists = db.execute("SELECT id FROM runs WHERE id = %s", (run_id,)).fetchone()
        if not exists:
            abort(404)
        stamp = now_iso()
        db.execute("""
            INSERT INTO run_ai_prompts (run_id, text, updated_at)
            VALUES (%s, %s, %s)
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
        lab = (request.form.get("lab") or "").strip().lower()
        content_json = (request.form.get("content_json") or "").strip() or None
        parent_raw = (request.form.get("parent") or "").strip()
        parent_type = parent_id = None
        if parent_raw and ":" in parent_raw:
            pt, pid = parent_raw.split(":", 1)
            if pt in ("experiment", "concept") and pid.isdigit():
                parent_type, parent_id = pt, int(pid)

        lab_values = {v for v, _ in LAB_OPTIONS}

        if not title:
            flash("The name of the experiment is required.", "error")
            with get_db() as db:
                parent_options = get_parent_options(db)
            return render_template("experiment_new.html", form_title=title, form_lab=lab, lab_options=LAB_OPTIONS, parent_options=parent_options, page_templates=PAGE_TEMPLATES)

        if lab not in lab_values:
            flash("Choose a lab group.", "error")
            with get_db() as db:
                parent_options = get_parent_options(db)
            return render_template("experiment_new.html", form_title=title, form_lab=lab, lab_options=LAB_OPTIONS, parent_options=parent_options, page_templates=PAGE_TEMPLATES)

        with get_db() as db:
            cur = db.execute("""
                INSERT INTO experiments (title, lab, content_json, parent_type, parent_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (title, lab, content_json, parent_type, parent_id, now_iso()))
            experiment_id = cur.fetchone()["id"]

        if content_json:
            link_media("experiment", experiment_id, content_json)

        log_activity("experiment", experiment_id, title, "created")
        flash("Your experiment is created.", "success")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))

    template_key = request.args.get("template")
    template_data = None
    if template_key and template_key in PAGE_TEMPLATES:
        template_data = json.dumps(PAGE_TEMPLATES[template_key]["data"])

    with get_db() as db:
        parent_options = get_parent_options(db)

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), ("New Experiment", None))
    return render_template("experiment_new.html", lab_options=LAB_OPTIONS, parent_options=parent_options, page_templates=PAGE_TEMPLATES, template_data=template_data, breadcrumbs=breadcrumbs)


@app.route("/experiment/<int:experiment_id>/edit", methods=["GET", "POST"])
def experiment_edit(experiment_id):
    with get_db() as db:
        exp = db.execute("SELECT * FROM experiments WHERE id = %s", (experiment_id,)).fetchone()
        if not exp:
            abort(404)

        if request.method == "POST":
            title = (request.form.get("title") or "").strip()
            lab = (request.form.get("lab") or "").strip().lower()
            content_json = (request.form.get("content_json") or "").strip() or None
            parent_raw = (request.form.get("parent") or "").strip()
            parent_type = parent_id = None
            if parent_raw and ":" in parent_raw:
                pt, pid = parent_raw.split(":", 1)
                if pt in ("experiment", "concept") and pid.isdigit():
                    parent_type, parent_id = pt, int(pid)

            lab_values = {v for v, _ in LAB_OPTIONS}
            if not title:
                flash("Title is required.", "error")
                parent_options = get_parent_options(db, "experiment", experiment_id)
                return render_template("experiment_edit.html", experiment=exp, lab_options=LAB_OPTIONS, parent_options=parent_options)
            if lab not in lab_values:
                flash("Choose a lab group.", "error")
                parent_options = get_parent_options(db, "experiment", experiment_id)
                return render_template("experiment_edit.html", experiment=exp, lab_options=LAB_OPTIONS, parent_options=parent_options)

            db.execute("""
                UPDATE experiments SET title = %s, lab = %s, content_json = %s, parent_type = %s, parent_id = %s
                WHERE id = %s
            """, (title, lab, content_json, parent_type, parent_id, experiment_id))

            if content_json:
                link_media("experiment", experiment_id, content_json)

            log_activity("experiment", experiment_id, title, "edited")
            flash("Experiment updated.", "success")
            return redirect(url_for("experiment", experiment_id=experiment_id, tab="overview"))

        parent_options = get_parent_options(db, "experiment", experiment_id)

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), (exp["title"], url_for("experiment", experiment_id=experiment_id, tab="overview")), ("Edit", None))
    return render_template("experiment_edit.html", experiment=exp, lab_options=LAB_OPTIONS, parent_options=parent_options, breadcrumbs=breadcrumbs)


@app.route("/experiment/<int:experiment_id>")
def experiment(experiment_id):
    tab = request.args.get("tab", "overview")

    with get_db() as db:
        exp = db.execute(
            "SELECT * FROM experiments WHERE id = %s",
            (experiment_id,),
        ).fetchone()
        if not exp:
            abort(404)
        setup = parse_setup(exp["setup_json"])
        content = parse_content_json(exp["content_json"])

        experiment_attachments = db.execute("""
            SELECT *
            FROM experiment_attachments
            WHERE experiment_id = %s
            ORDER BY created_at DESC, id DESC
        """, (experiment_id,)).fetchall()
        ai_prompt = db.execute("""
            SELECT *
            FROM experiment_ai_prompts
            WHERE experiment_id = %s
        """, (experiment_id,)).fetchone()

        runs = db.execute("""
            SELECT r.*,
                   (SELECT COUNT(*) FROM attachments a WHERE a.run_id = r.id) AS attachments_count
            FROM runs r
            WHERE r.experiment_id = %s
            ORDER BY r.created_at DESC, r.id DESC
        """, (experiment_id,)).fetchall()

        recent_attachments = db.execute("""
            SELECT a.*, r.title AS run_title
            FROM attachments a
            JOIN runs r ON r.id = a.run_id
            WHERE r.experiment_id = %s
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 6
        """, (experiment_id,)).fetchall()

        entity_tags = get_entity_tags(db, "experiment", experiment_id)
        all_tags = get_all_tags(db)
        ancestors = get_ancestor_chain(db, exp["parent_type"], exp["parent_id"])

    crumbs = [("Home", url_for("index"))]
    for atype, aid, atitle in ancestors:
        if atype == "experiment":
            crumbs.append((atitle, url_for("experiment", experiment_id=aid, tab="overview")))
        else:
            crumbs.append((atitle, url_for("concept_view", concept_id=aid)))
    crumbs.append((exp["title"], None))
    breadcrumbs = make_breadcrumbs(*crumbs)

    return render_template(
        "experiment.html",
        experiment=exp,
        setup=setup,
        content=content,
        runs=runs,
        tab=tab,
        recent_attachments=recent_attachments,
        experiment_attachments=experiment_attachments,
        ai_prompt=ai_prompt,
        entity_tags=entity_tags,
        all_tags=all_tags,
        breadcrumbs=breadcrumbs,
        tag_colors=TAG_COLORS,
    )


@app.route("/experiment/<int:experiment_id>/run/new", methods=["GET", "POST"])
def run_new(experiment_id):
    with get_db() as db:
        exp = db.execute(
            "SELECT * FROM experiments WHERE id = %s",
            (experiment_id,),
        ).fetchone()
    if not exp:
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content_json = (request.form.get("content_json") or "").strip() or None

        if not title:
            flash("The name of the run is required.", "error")
            return render_template("run_new.html", experiment=exp, form_title=title)

        with get_db() as db:
            cur = db.execute("""
                INSERT INTO runs (experiment_id, title, content_json, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (experiment_id, title, content_json, now_iso()))
            run_id = cur.fetchone()["id"]

        if content_json:
            link_media("run", run_id, content_json)

        log_activity("run", run_id, title, "created")
        flash("Run is saved.", "success")
        return redirect(url_for("experiment", experiment_id=experiment_id, tab="results"))

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), (exp["title"], url_for("experiment", experiment_id=experiment_id, tab="overview")), ("New Run", None))
    return render_template("run_new.html", experiment=exp, breadcrumbs=breadcrumbs)


@app.route("/run/<int:run_id>/edit", methods=["GET", "POST"])
def run_edit(run_id):
    with get_db() as db:
        run = db.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
        if not run:
            abort(404)
        exp = db.execute("SELECT * FROM experiments WHERE id = %s", (run["experiment_id"],)).fetchone()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content_json = (request.form.get("content_json") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return render_template("run_edit.html", run=run, experiment=exp)

        with get_db() as db:
            db.execute("""
                UPDATE runs SET title = %s, content_json = %s
                WHERE id = %s
            """, (title, content_json, run_id))

        if content_json:
            link_media("run", run_id, content_json)

        log_activity("run", run_id, title, "edited")
        flash("Run updated.", "success")
        return redirect(url_for("run_view", run_id=run_id))

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), (exp["title"], url_for("experiment", experiment_id=exp["id"], tab="overview")), (run["title"], url_for("run_view", run_id=run_id)), ("Edit", None))
    return render_template("run_edit.html", run=run, experiment=exp, breadcrumbs=breadcrumbs)


@app.route("/run/<int:run_id>")
def run_view(run_id):
    with get_db() as db:
        run = db.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
        if not run:
            abort(404)
        exp = db.execute("SELECT * FROM experiments WHERE id = %s", (run["experiment_id"],)).fetchone()
        if not exp:
            abort(404)
        setup = parse_setup(run["setup_json"])
        content = parse_content_json(run["content_json"])
        ai_prompt = db.execute("""
            SELECT *
            FROM run_ai_prompts
            WHERE run_id = %s
        """, (run_id,)).fetchone()
        attachments = db.execute("""
            SELECT *
            FROM attachments
            WHERE run_id = %s
            ORDER BY created_at DESC, id DESC
        """, (run_id,)).fetchall()

        entity_tags = get_entity_tags(db, "run", run_id)
        all_tags = get_all_tags(db)

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), (exp["title"], url_for("experiment", experiment_id=exp["id"], tab="overview")), (run["title"], None))

    return render_template(
        "run_view.html",
        experiment=exp,
        run=run,
        content=content,
        attachments=attachments,
        setup=setup,
        ai_prompt=ai_prompt,
        entity_tags=entity_tags,
        all_tags=all_tags,
        breadcrumbs=breadcrumbs,
        tag_colors=TAG_COLORS,
    )


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)


@app.route("/attachment/<int:attachment_id>/download")
def attachment_download(attachment_id):
    with get_db() as db:
        att = db.execute("SELECT * FROM attachments WHERE id = %s", (attachment_id,)).fetchone()
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
        att = db.execute("SELECT * FROM experiment_attachments WHERE id = %s", (attachment_id,)).fetchone()
    if not att:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR,
        att["stored_name"],
        as_attachment=True,
        download_name=att["original_name"],
    )


@app.post("/api/upload")
def api_upload():
    f = request.files.get("image") or request.files.get("file")
    if not f or not f.filename:
        return jsonify(success=0, message="No file provided"), 400
    if not allowed_file(f.filename):
        return jsonify(success=0, message="File type not allowed"), 400

    stored = unique_store_name(f.filename)
    f.save(UPLOAD_DIR / stored)

    size = f.content_length or 0
    with get_db() as db:
        db.execute("""
            INSERT INTO media (stored_name, original_name, mime, size_bytes, entity_type, entity_id, created_at)
            VALUES (%s, %s, %s, %s, '', NULL, %s)
        """, (stored, f.filename, f.mimetype, size, now_iso()))

    return jsonify(success=1, file={
        "url": url_for("uploads", filename=stored),
        "name": f.filename,
        "size": size,
    })


## --- Tag API routes ---

@app.post("/api/tags")
def api_tag_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "blue").strip()
    if not name:
        return jsonify(success=False, message="Tag name required"), 400
    if color not in TAG_COLORS:
        color = "blue"
    with get_db() as db:
        existing = db.execute("SELECT id FROM tags WHERE name = %s", (name,)).fetchone()
        if existing:
            return jsonify(success=True, tag={"id": existing["id"], "name": name, "color": color})
        cur = db.execute("INSERT INTO tags (name, color) VALUES (%s, %s) RETURNING id", (name, color))
        tag_id = cur.fetchone()["id"]
    return jsonify(success=True, tag={"id": tag_id, "name": name, "color": color})


@app.post("/api/entity/<entity_type>/<int:entity_id>/tag")
def api_entity_tag_add(entity_type, entity_id):
    if entity_type not in ("experiment", "concept", "run"):
        return jsonify(success=False, message="Invalid entity type"), 400
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    if not tag_id:
        return jsonify(success=False, message="tag_id required"), 400
    with get_db() as db:
        db.execute("""
            INSERT INTO entity_tags (entity_type, entity_id, tag_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (entity_type, entity_id, int(tag_id)))
    return jsonify(success=True)


@app.post("/api/entity/<entity_type>/<int:entity_id>/tag/<int:tag_id>/remove")
def api_entity_tag_remove(entity_type, entity_id, tag_id):
    if entity_type not in ("experiment", "concept", "run"):
        return jsonify(success=False, message="Invalid entity type"), 400
    with get_db() as db:
        db.execute("""
            DELETE FROM entity_tags
            WHERE entity_type = %s AND entity_id = %s AND tag_id = %s
        """, (entity_type, entity_id, tag_id))
    return jsonify(success=True)


## --- Duplicate routes ---

@app.post("/experiment/<int:experiment_id>/duplicate")
def experiment_duplicate(experiment_id):
    with get_db() as db:
        exp = db.execute("SELECT * FROM experiments WHERE id = %s", (experiment_id,)).fetchone()
        if not exp:
            abort(404)
        stamp = now_iso()
        new_title = "Copy of " + exp["title"]
        cur = db.execute("""
            INSERT INTO experiments (title, lab, content_json, parent_type, parent_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (new_title, exp["lab"], exp["content_json"], exp["parent_type"], exp["parent_id"], stamp))
        new_id = cur.fetchone()["id"]

        # Copy tags
        tags = db.execute("SELECT tag_id FROM entity_tags WHERE entity_type = 'experiment' AND entity_id = %s", (experiment_id,)).fetchall()
        for t in tags:
            db.execute("""
                INSERT INTO entity_tags (entity_type, entity_id, tag_id)
                VALUES ('experiment', %s, %s)
                ON CONFLICT DO NOTHING
            """, (new_id, t["tag_id"]))

    if exp["content_json"]:
        link_media("experiment", new_id, exp["content_json"])
    log_activity("experiment", new_id, new_title, "duplicated")
    flash("Experiment duplicated.", "success")
    return redirect(url_for("experiment", experiment_id=new_id, tab="overview"))


@app.post("/concept/<int:concept_id>/duplicate")
def concept_duplicate(concept_id):
    with get_db() as db:
        concept = db.execute("SELECT * FROM concepts WHERE id = %s", (concept_id,)).fetchone()
        if not concept:
            abort(404)
        stamp = now_iso()
        new_title = "Copy of " + concept["title"]
        cur = db.execute("""
            INSERT INTO concepts (title, author, content_json, parent_type, parent_id, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (new_title, concept["author"], concept["content_json"], concept["parent_type"], concept["parent_id"], stamp, stamp))
        new_id = cur.fetchone()["id"]

        tags = db.execute("SELECT tag_id FROM entity_tags WHERE entity_type = 'concept' AND entity_id = %s", (concept_id,)).fetchall()
        for t in tags:
            db.execute("""
                INSERT INTO entity_tags (entity_type, entity_id, tag_id)
                VALUES ('concept', %s, %s)
                ON CONFLICT DO NOTHING
            """, (new_id, t["tag_id"]))

    if concept["content_json"]:
        link_media("concept", new_id, concept["content_json"])
    log_activity("concept", new_id, new_title, "duplicated")
    flash("Concept duplicated.", "success")
    return redirect(url_for("concept_view", concept_id=new_id))


## --- Compare (split-view) routes ---

@app.route("/compare")
def compare():
    left_id = request.args.get("left", type=int)
    right_id = request.args.get("right", type=int)
    if not left_id or not right_id:
        flash("Select two experiments to compare.", "error")
        return redirect(url_for("index"))
    with get_db() as db:
        left = db.execute("SELECT * FROM experiments WHERE id = %s", (left_id,)).fetchone()
        right = db.execute("SELECT * FROM experiments WHERE id = %s", (right_id,)).fetchone()
        if not left or not right:
            flash("One or both experiments not found.", "error")
            return redirect(url_for("index"))
        left_content = parse_content_json(left["content_json"])
        right_content = parse_content_json(right["content_json"])
        left_ai = db.execute("SELECT * FROM experiment_ai_prompts WHERE experiment_id = %s", (left_id,)).fetchone()
        right_ai = db.execute("SELECT * FROM experiment_ai_prompts WHERE experiment_id = %s", (right_id,)).fetchone()

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), ("Compare", None))
    return render_template(
        "compare.html",
        left=left, right=right,
        left_content=left_content, right_content=right_content,
        left_ai=left_ai, right_ai=right_ai,
        breadcrumbs=breadcrumbs,
    )


@app.post("/compare/ai")
def compare_ai_save():
    left_id = request.form.get("left_id", type=int)
    right_id = request.form.get("right_id", type=int)
    text = (request.form.get("text") or "").strip()
    if not text:
        flash("Prompt cannot be empty.", "error")
        return redirect(url_for("compare", left=left_id, right=right_id))

    stamp = now_iso()
    with get_db() as db:
        for eid in (left_id, right_id):
            if eid:
                db.execute("""
                    INSERT INTO experiment_ai_prompts (experiment_id, text, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(experiment_id) DO UPDATE SET
                      text=excluded.text,
                      updated_at=excluded.updated_at
                """, (eid, text, stamp))
    flash("Prompt saved to both experiments.", "success")
    return redirect(url_for("compare", left=left_id, right=right_id))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
