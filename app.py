import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import re

from dotenv import load_dotenv

load_dotenv()

from groq import Groq
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

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

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
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                entity_type TEXT,
                entity_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_entity
            ON chat_messages (entity_type, entity_id)
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


# --------------- AI Chat helpers ---------------

def extract_text_from_blocks(content_json_str):
    """Convert Editor.js JSON to plain text for AI context."""
    if not content_json_str:
        return ""
    try:
        data = json.loads(content_json_str)
    except Exception:
        return ""
    blocks = data.get("blocks", []) if isinstance(data, dict) else []
    parts = []
    for b in blocks:
        btype = b.get("type", "")
        bd = b.get("data", {})
        if btype in ("paragraph", "header"):
            text = re.sub(r"<[^>]+>", "", bd.get("text", ""))
            parts.append(text)
        elif btype == "list":
            for item in bd.get("items", []):
                if isinstance(item, dict):
                    parts.append(re.sub(r"<[^>]+>", "", item.get("content", "")))
                else:
                    parts.append(re.sub(r"<[^>]+>", "", str(item)))
        elif btype == "table":
            for row in bd.get("content", []):
                parts.append(" | ".join(re.sub(r"<[^>]+>", "", c) for c in row))
        elif btype == "quote":
            parts.append(re.sub(r"<[^>]+>", "", bd.get("text", "")))
        elif btype == "code":
            parts.append(bd.get("code", ""))
        elif btype == "checklist":
            for item in bd.get("items", []):
                if isinstance(item, dict):
                    prefix = "[x] " if item.get("checked") else "[ ] "
                    parts.append(prefix + re.sub(r"<[^>]+>", "", item.get("text", "")))
    return "\n".join(parts)


def build_project_context(db, entity_type=None, entity_id=None):
    """Build a text summary of all project data for the AI prompt."""
    sections = []

    # Current entity first (higher priority)
    if entity_type and entity_id:
        if entity_type == "experiment":
            exp = db.execute("SELECT * FROM experiments WHERE id = %s", (entity_id,)).fetchone()
            if exp:
                sections.append(f"=== CURRENT EXPERIMENT (id={exp['id']}) ===")
                sections.append(f"Title: {exp['title']}")
                sections.append(f"Lab: {exp['lab'] or 'N/A'}")
                sections.append(f"Created: {exp['created_at']}")
                sections.append(extract_text_from_blocks(exp["content_json"]))
                runs = db.execute("SELECT * FROM runs WHERE experiment_id = %s ORDER BY created_at", (entity_id,)).fetchall()
                for r in runs:
                    sections.append(f"\n-- Run: {r['title']} (created {r['created_at']}) --")
                    sections.append(extract_text_from_blocks(r["content_json"]))
        elif entity_type == "run":
            run = db.execute("SELECT * FROM runs WHERE id = %s", (entity_id,)).fetchone()
            if run:
                exp = db.execute("SELECT * FROM experiments WHERE id = %s", (run["experiment_id"],)).fetchone()
                sections.append(f"=== CURRENT RUN (id={run['id']}) ===")
                sections.append(f"Title: {run['title']}")
                sections.append(f"Experiment: {exp['title'] if exp else 'N/A'}")
                sections.append(f"Created: {run['created_at']}")
                sections.append(extract_text_from_blocks(run["content_json"]))
        elif entity_type == "concept":
            concept = db.execute("SELECT * FROM concepts WHERE id = %s", (entity_id,)).fetchone()
            if concept:
                sections.append(f"=== CURRENT CONCEPT (id={concept['id']}) ===")
                sections.append(f"Title: {concept['title']}")
                sections.append(f"Author: {concept['author']}")
                sections.append(f"Updated: {concept['updated_at']}")
                sections.append(extract_text_from_blocks(concept["content_json"]))

    # All experiments
    experiments = db.execute("SELECT * FROM experiments ORDER BY created_at DESC").fetchall()
    sections.append("\n=== ALL EXPERIMENTS ===")
    for exp in experiments:
        sections.append(f"\n[Experiment id={exp['id']}] {exp['title']} | Lab: {exp['lab'] or 'N/A'} | Created: {exp['created_at']}")
        text = extract_text_from_blocks(exp["content_json"])
        if text:
            sections.append(text)
        runs = db.execute("SELECT * FROM runs WHERE experiment_id = %s ORDER BY created_at", (exp["id"],)).fetchall()
        for r in runs:
            sections.append(f"  [Run id={r['id']}] {r['title']} | Created: {r['created_at']}")
            rtext = extract_text_from_blocks(r["content_json"])
            if rtext:
                sections.append("  " + rtext.replace("\n", "\n  "))

    # All concepts
    concepts = db.execute("SELECT * FROM concepts ORDER BY updated_at DESC").fetchall()
    if concepts:
        sections.append("\n=== ALL CONCEPTS ===")
        for c in concepts:
            sections.append(f"\n[Concept id={c['id']}] {c['title']} | Author: {c['author']} | Updated: {c['updated_at']}")
            text = extract_text_from_blocks(c["content_json"])
            if text:
                sections.append(text)

    # Tags
    tags = db.execute("""
        SELECT t.name, t.color, et.entity_type, et.entity_id
        FROM tags t
        LEFT JOIN entity_tags et ON et.tag_id = t.id
        ORDER BY t.name
    """).fetchall()
    if tags:
        sections.append("\n=== TAGS ===")
        for t in tags:
            sections.append(f"Tag '{t['name']}' ({t['color']}) -> {t['entity_type']} id={t['entity_id']}")

    # Recent activity
    activity = db.execute("""
        SELECT * FROM activity_log ORDER BY created_at DESC LIMIT 30
    """).fetchall()
    if activity:
        sections.append("\n=== RECENT ACTIVITY ===")
        for a in activity:
            sections.append(f"{a['created_at']} | {a['action']} {a['entity_type']} '{a['entity_title']}'")

    return "\n".join(sections)


def get_chat_history(db, entity_type, entity_id, limit=20):
    """Fetch recent chat messages for an entity."""
    if entity_type and entity_id:
        rows = db.execute("""
            SELECT role, content, created_at FROM chat_messages
            WHERE entity_type = %s AND entity_id = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
        """, (entity_type, entity_id, limit)).fetchall()
    else:
        rows = db.execute("""
            SELECT role, content, created_at FROM chat_messages
            WHERE entity_type IS NULL AND entity_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT %s
        """, (limit,)).fetchall()
    return list(reversed(rows))


def save_chat_message(db, entity_type, entity_id, role, content):
    db.execute("""
        INSERT INTO chat_messages (entity_type, entity_id, role, content, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """, (entity_type or None, entity_id or None, role, content, now_iso()))
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


## --- AI Chat routes ---

@app.post("/ai/chat")
def ai_chat():
    if not groq_client:
        return jsonify({"error": "GROQ_API_KEY not configured"}), 500

    data = request.get_json()
    if not data or not data.get("message", "").strip():
        return jsonify({"error": "Message is required"}), 400

    user_message = data["message"].strip()
    entity_type = data.get("entity_type") or None
    entity_id = data.get("entity_id") or None

    with get_db() as db:
        context = build_project_context(db, entity_type, entity_id)
        history = get_chat_history(db, entity_type, entity_id, limit=10)

        system_prompt = (
            "You are the AI Lab Manager assistant for the R&D research team. "
            "You help researchers understand their experiments, runs, and concepts. "
            "Answer based on the project data provided below. If you don't have enough information, say so. "
            "Be concise and specific. Reference experiment/concept titles when relevant.\n\n"
            f"PROJECT DATA:\n{context}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({
                "role": msg["role"] if msg["role"] == "user" else "assistant",
                "content": msg["content"],
            })
        messages.append({"role": "user", "content": user_message})

        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
            )
            reply = response.choices[0].message.content
        except Exception as e:
            return jsonify({"error": f"Groq API error: {str(e)}"}), 502

        save_chat_message(db, entity_type, entity_id, "user", user_message)
        save_chat_message(db, entity_type, entity_id, "assistant", reply)

    return jsonify({"reply": reply})


@app.get("/ai/history")
def ai_history():
    entity_type = request.args.get("entity_type") or None
    entity_id = request.args.get("entity_id", type=int) or None
    with get_db() as db:
        messages = get_chat_history(db, entity_type, entity_id, limit=50)
    return jsonify([dict(m) for m in messages])


@app.post("/ai/clear")
def ai_clear():
    data = request.get_json() or {}
    entity_type = data.get("entity_type") or None
    entity_id = data.get("entity_id") or None
    with get_db() as db:
        if entity_type and entity_id:
            db.execute(
                "DELETE FROM chat_messages WHERE entity_type = %s AND entity_id = %s",
                (entity_type, entity_id),
            )
        else:
            db.execute(
                "DELETE FROM chat_messages WHERE entity_type IS NULL AND entity_id IS NULL",
            )
    return jsonify({"ok": True})


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

    breadcrumbs = make_breadcrumbs(("Home", url_for("index")), ("Compare", None))
    return render_template(
        "compare.html",
        left=left, right=right,
        left_content=left_content, right_content=right_content,
        breadcrumbs=breadcrumbs,
    )


def seed_mock_data():
    """Populate the DB with a coherent robotics project for AI chat testing."""
    with get_db() as db:
        if db.execute("SELECT COUNT(*) AS c FROM experiments").fetchone()["c"] > 0:
            print("Database not empty — skipping seed. Drop tables first if you want to reseed.")
            return

    print("Seeding mock data: Bio-Inspired Soft Robotic Gripper project...")

    # --- Tags ---
    tag_ids = {}
    tag_defs = [
        ("hydrogel", "blue"), ("simulation", "purple"), ("fabrication", "amber"),
        ("control", "green"), ("biocompat", "pink"), ("benchmark", "teal"),
        ("phase-1", "gray"), ("phase-2", "gray"), ("phase-3", "gray"),
    ]
    with get_db() as db:
        for name, color in tag_defs:
            cur = db.execute(
                "INSERT INTO tags (name, color) VALUES (%s, %s) RETURNING id",
                (name, color),
            )
            tag_ids[name] = cur.fetchone()["id"]

    def _editor(blocks):
        return json.dumps({"time": int(time.time() * 1000), "blocks": blocks, "version": "2.28.0"})

    def _p(text):
        return {"type": "paragraph", "data": {"text": text}}

    def _h(text, level=2):
        return {"type": "header", "data": {"text": text, "level": level}}

    def _ul(items):
        return {"type": "list", "data": {"style": "unordered", "items": items}}

    def _ol(items):
        return {"type": "list", "data": {"style": "ordered", "items": items}}

    def _table(headers, rows):
        return {"type": "table", "data": {"withHeadings": True, "content": [headers] + rows}}

    def _check(items):
        return {"type": "checklist", "data": {"items": [{"text": t, "checked": c} for t, c in items]}}

    # =========================================================================
    # PHASE 1 — Material Research & Initial Simulations (Jan 2026)
    # =========================================================================

    exp1_wet = _editor([
        _h("Objective"),
        _p("Synthesize and characterize PNIPAAm-based hydrogels for use as thermo-responsive actuators in a soft robotic gripper. "
           "Evaluate swelling ratios, response time, and mechanical strength across three formulations."),
        _h("Materials"),
        _ul(["N-isopropylacrylamide (NIPAAm) monomer, 98% purity",
             "N,N'-methylenebisacrylamide (MBA) crosslinker",
             "Ammonium persulfate (APS) initiator",
             "TEMED catalyst",
             "Deionized water",
             "Phosphate-buffered saline (PBS, pH 7.4)"]),
        _h("Protocol"),
        _ol(["Dissolve NIPAAm in DI water at 3 concentrations: 5%, 10%, 15% (w/v)",
             "Add MBA crosslinker at 1:50 molar ratio to monomer",
             "Degas solution under nitrogen for 30 min",
             "Add APS (0.1% w/v) and TEMED (0.05% v/v) to initiate polymerization",
             "Pour into cylindrical molds (d=10mm, h=5mm), cure at 25°C for 4 hours",
             "Wash gels in DI water for 48h, changing water every 12h",
             "Characterize swelling ratio by gravimetric analysis at 25°C and 40°C",
             "Measure Young's modulus via compression testing (Instron 5944)"]),
        _h("Setup / Conditions"),
        _table(
            ["Parameter", "Formulation A", "Formulation B", "Formulation C"],
            [["NIPAAm conc.", "5% w/v", "10% w/v", "15% w/v"],
             ["MBA ratio", "1:50", "1:50", "1:50"],
             ["Cure time", "4 h", "4 h", "4 h"],
             ["Cure temp", "25°C", "25°C", "25°C"],
             ["LCST target", "~32°C", "~32°C", "~32°C"]]),
        _h("Results"),
        _p("Formulation B (10% NIPAAm) showed the best balance of properties: "
           "swelling ratio of 12.3 at 25°C with rapid deswelling (85% volume change within 90 seconds at 40°C). "
           "Formulation A was too soft (Young's modulus 2.1 kPa) for gripper actuation. "
           "Formulation C had high stiffness (48 kPa) but slow response time (>5 min for full deswelling)."),
        _table(
            ["Metric", "Form. A (5%)", "Form. B (10%)", "Form. C (15%)"],
            [["Swelling ratio (25°C)", "18.7", "12.3", "6.1"],
             ["Deswelling time (40°C)", "45 s", "90 s", "320 s"],
             ["Young's modulus", "2.1 kPa", "15.8 kPa", "48.2 kPa"],
             ["Volume change %", "92%", "85%", "61%"]]),
        _h("Conclusions"),
        _p("Formulation B selected for gripper prototyping. Next step: optimize crosslinker ratio for faster response time "
           "while maintaining mechanical integrity. Consider adding nanoclay reinforcement."),
    ])

    exp1_dry = _editor([
        _h("Objective"),
        _p("Develop a finite element model (FEA) of a 3-finger soft gripper geometry to predict bending behavior "
           "under thermal actuation. Compare radial vs. bilayer actuator configurations."),
        _h("Tools & Versions"),
        _ul(["COMSOL Multiphysics 6.2 (Structural + Heat Transfer modules)",
             "MATLAB R2025b (post-processing and parameter sweeps)",
             "Python 3.11 + meshio (mesh conversion)",
             "Paraview 5.12 (visualization)"]),
        _h("Simulation Parameters"),
        _table(
            ["Parameter", "Value", "Source"],
            [["Hydrogel E (swollen)", "15.8 kPa", "Experimental (Form. B)"],
             ["Hydrogel E (deswollen)", "42.0 kPa", "Literature estimate"],
             ["Poisson's ratio", "0.45", "Literature (rubber-like)"],
             ["Thermal expansion coeff.", "-0.028 /°C", "Fitted from swelling data"],
             ["Finger length", "60 mm", "Design spec"],
             ["Finger diameter", "12 mm", "Design spec"],
             ["PDMS backing E", "1.8 MPa", "Sylgard 184 datasheet"]]),
        _h("Results"),
        _p("The bilayer configuration (hydrogel on PDMS backing) produced significantly better bending: "
           "tip deflection of 23.4 mm at ΔT=15°C vs. only 8.2 mm for the radial design. "
           "The bilayer design generates a bending moment due to differential expansion, similar to a bimetallic strip."),
        _p("Stress analysis shows peak von Mises stress of 12.3 kPa at the hydrogel-PDMS interface, "
           "well below the measured gel failure stress of 35 kPa. Safety factor = 2.8."),
        _h("Parameter Sweep"),
        _table(
            ["Backing thickness (mm)", "Tip deflection (mm)", "Max stress (kPa)", "Response time (s)"],
            [["0.5", "31.2", "18.7", "65"],
             ["1.0", "23.4", "12.3", "82"],
             ["1.5", "16.8", "9.1", "105"],
             ["2.0", "11.3", "6.8", "130"]]),
        _p("1.0 mm PDMS backing selected as optimal — good deflection with acceptable stress margin and response time under 90s."),
        _h("Conclusions"),
        _p("Bilayer configuration validated. FEA model correlates well with literature bending data (R²=0.94). "
           "Ready to proceed with physical prototyping using Form. B hydrogel + 1mm PDMS backing."),
    ])

    # Runs for Phase 1
    run1_wet_a = _editor([
        _h("Run 1: Initial Synthesis Batch"),
        _p("Prepared all three formulations (A, B, C). Polymerization successful for B and C. "
           "Formulation A gels were extremely fragile — two out of five samples broke during demolding."),
        _h("Observations"),
        _ul(["Form. A: transparent, very soft, difficult to handle",
             "Form. B: translucent, firm but flexible, good handleability",
             "Form. C: opaque white, stiff, slightly brittle at edges"]),
        _p("Swelling measurements started. Samples placed in PBS at 25°C."),
    ])

    run1_wet_b = _editor([
        _h("Run 2: Thermal Response Characterization"),
        _p("Measured deswelling kinetics by immersing swollen gels in 40°C water bath and recording mass at 15s intervals."),
        _h("Key Findings"),
        _ul(["Form. B reached 50% deswelling in 38 seconds — fastest initial response",
             "Form. C showed a lag phase of ~60s before significant deswelling began",
             "Form. A collapsed too quickly — complete deswelling in 45s but samples curled and deformed",
             "All samples returned to original swollen state within 10 min at 25°C (good reversibility)"]),
        _p("Compression testing completed on Instron. Form. B shows linear elastic behavior up to 30% strain."),
    ])

    run1_dry_a = _editor([
        _h("Run 1: Mesh Convergence Study"),
        _p("Ran mesh convergence analysis on the bilayer finger model. Tested element sizes from 2mm down to 0.25mm."),
        _table(
            ["Element size (mm)", "Nodes", "Tip deflection (mm)", "Solve time (s)"],
            [["2.0", "1,240", "19.8", "3"],
             ["1.0", "4,830", "22.9", "12"],
             ["0.5", "18,620", "23.4", "48"],
             ["0.25", "72,400", "23.5", "310"]]),
        _p("Converged at 0.5mm element size (0.4% difference from finest mesh). Used for all subsequent simulations."),
    ])

    run1_dry_b = _editor([
        _h("Run 2: Radial vs Bilayer Comparison"),
        _p("Full comparison of both actuator topologies under identical loading (ΔT = 5°C, 10°C, 15°C)."),
        _h("Results"),
        _p("Bilayer outperforms radial at all temperature differences. The advantage grows nonlinearly — "
           "at ΔT=15°C the bilayer produces 2.85x the deflection of radial."),
        _ul(["Radial design shows uniform expansion but poor bending — acts more like a balloon",
             "Bilayer produces clean, predictable curling motion ideal for gripping",
             "Contact force analysis: bilayer can exert 0.18 N at fingertip vs 0.05 N for radial"]),
    ])

    # =========================================================================
    # PHASE 2 — Prototyping & Control (Feb 2026)
    # =========================================================================

    exp2_wet = _editor([
        _h("Objective"),
        _p("Fabricate a 3-finger bilayer gripper prototype using Formulation B hydrogel on PDMS backing. "
           "Test grip force, repeatability, and thermal cycling durability."),
        _h("Materials"),
        _ul(["Formulation B hydrogel (10% NIPAAm, 1:50 MBA)",
             "Sylgard 184 PDMS kit (10:1 base:curing agent)",
             "3D-printed PLA finger molds (Prusa MK4S, 0.15mm layer height)",
             "Nichrome heating wire (0.2mm diameter)",
             "Kapton tape for wire insulation",
             "Silicone adhesive (Sil-Poxy)",
             "Arduino Nano for heater control"]),
        _h("Fabrication Protocol"),
        _ol(["Cast PDMS backing layers: pour degassed Sylgard 184 into molds, cure at 65°C for 2h, target 1.0mm thickness",
             "Surface-treat PDMS with oxygen plasma (30s, 50W) for hydrogel adhesion",
             "Embed nichrome heating wire in serpentine pattern on PDMS surface using Kapton guides",
             "Pour NIPAAm pre-polymer solution over PDMS+wire assembly",
             "Cure hydrogel at 25°C for 4h under nitrogen atmosphere",
             "Assemble 3 fingers onto 3D-printed PLA hub with 120° spacing",
             "Connect heating wires to Arduino Nano via MOSFET driver board"]),
        _h("Test Protocol"),
        _ol(["Submerge gripper in 25°C water bath",
             "Apply 5V to heating wires (target: raise gel temp to 40°C in <60s)",
             "Record bending angle via side-view camera at 5s intervals",
             "Test grip on standardized objects: 20mm foam cube, 15mm rubber ball, 10mm glass bead",
             "Repeat open-close cycle 100 times, measure force degradation"]),
        _h("Results"),
        _p("Prototype successfully grips all three test objects. Heating wire reaches 40°C in 45 seconds. "
           "Fingers achieve 22° bending angle, close to the simulated 23.4mm tip deflection prediction."),
        _table(
            ["Metric", "Value", "Target", "Status"],
            [["Bending angle", "22°", "20°", "PASS"],
             ["Heat-up time", "45 s", "<60 s", "PASS"],
             ["Cool-down time", "110 s", "<120 s", "PASS"],
             ["Grip force (foam cube)", "0.15 N", ">0.1 N", "PASS"],
             ["Grip force (glass bead)", "0.08 N", ">0.1 N", "FAIL"],
             ["Cycle durability (100x)", "12% force loss", "<10%", "MARGINAL"]]),
        _h("Conclusions"),
        _p("Prototype validates the bilayer concept. Glass bead gripping fails due to smooth surface and small diameter — "
           "consider adding micro-texture to finger contact surfaces. "
           "Force degradation after 100 cycles suggests hydrogel fatigue — nanoclay reinforcement should be investigated. "
           "Heating wire approach works but is bulky; Peltier elements could be more compact for final design."),
    ])

    exp2_dry = _editor([
        _h("Objective"),
        _p("Develop a closed-loop PID temperature controller for the gripper and implement a basic grip-release sequence. "
           "Test on hardware-in-the-loop simulation before deploying to physical prototype."),
        _h("Software Stack"),
        _ul(["Python 3.11 with NumPy, SciPy",
             "Arduino firmware (C++) for low-level heater PWM",
             "Serial communication (pyserial) between PC and Arduino",
             "OpenCV 4.9 for bending angle measurement from camera feed",
             "Matplotlib for real-time plotting"]),
        _h("Control Architecture"),
        _p("Two-level control: inner PID loop controls temperature (Arduino-side, 100Hz), "
           "outer state machine manages grip sequence (Python-side, 10Hz). "
           "Temperature feedback from NTC thermistor embedded near heating wire."),
        _h("PID Tuning"),
        _table(
            ["Parameter", "Initial", "Tuned", "Method"],
            [["Kp", "2.0", "3.5", "Ziegler-Nichols"],
             ["Ki", "0.5", "0.8", "Ziegler-Nichols"],
             ["Kd", "0.1", "0.25", "Manual refinement"],
             ["Setpoint", "40°C", "40°C", "—"],
             ["Overshoot", "8.2°C", "1.4°C", "—"],
             ["Settling time", "62 s", "38 s", "—"]]),
        _h("State Machine"),
        _ol(["IDLE: fingers open, heaters off, T ≈ 25°C",
             "CLOSING: ramp temperature to 40°C, monitor bending angle via camera",
             "GRIPPING: hold temperature, detect stable contact (angle plateau for 2s)",
             "HOLDING: maintain grip, reduce heater power to sustain mode (saves ~40% energy)",
             "RELEASING: cut heater power, wait for T < 28°C, confirm fingers open",
             "Return to IDLE"]),
        _h("Results"),
        _p("Controller achieves stable temperature regulation with ±0.5°C accuracy after tuning. "
           "Full grip cycle takes 180s (45s close, 15s stabilize, variable hold, 110s open). "
           "Camera-based angle detection works reliably at 10 fps — median error 0.8° vs manual measurement."),
        _h("Conclusions"),
        _p("Control system ready for physical prototype deployment. Main limitation: cooling is passive (ambient water). "
           "Active cooling (Peltier or forced convection) would reduce cycle time to ~60s. "
           "Consider adding force sensor feedback for delicate object handling."),
    ])

    run2_wet_a = _editor([
        _h("Run 1: PDMS Backing Fabrication"),
        _p("Cast six PDMS backing strips (2 spares). Measured thickness with digital calipers."),
        _table(
            ["Sample", "Thickness (mm)", "Within spec?"],
            [["F1-L", "0.98", "Yes"], ["F1-R", "1.05", "Yes"],
             ["F2-L", "0.92", "Yes"], ["F2-R", "1.12", "Marginal"],
             ["Spare-1", "1.01", "Yes"], ["Spare-2", "0.88", "No — too thin"]]),
        _p("Oxygen plasma treatment applied to all samples. Water contact angle dropped from 108° to 23° — good activation. "
           "Treatment window is ~30 min before hydrophobic recovery, so hydrogel casting must follow immediately."),
    ])

    run2_wet_b = _editor([
        _h("Run 2: Gripper Assembly and First Grip Tests"),
        _p("Assembled the 3-finger gripper. Two fingers bonded well; Finger 2 showed partial delamination at one corner after 24h curing. "
           "Applied Sil-Poxy reinforcement at the interface — held during testing."),
        _h("Grip Test Results"),
        _table(
            ["Object", "Diameter", "Weight", "Grip success (5 trials)", "Notes"],
            [["Foam cube", "20 mm", "1.2 g", "5/5", "Easy grip, good conformity"],
             ["Rubber ball", "15 mm", "3.8 g", "4/5", "1 slip at initial contact"],
             ["Glass bead", "10 mm", "1.4 g", "1/5", "Too smooth, fingers slide off"],
             ["Cherry tomato", "25 mm", "8.1 g", "3/5", "Fragile — 1 crushed at full force"]]),
        _p("Glass bead results confirm the need for textured contact surfaces. "
           "Tomato test is promising but needs force-limited grip mode."),
    ])

    run2_dry_a = _editor([
        _h("Run 1: PID Tuning Session"),
        _p("Used Ziegler-Nichols method on the physical prototype. Applied step input from 25°C to 40°C."),
        _h("Tuning Process"),
        _ol(["Set Ki=0, Kd=0. Increased Kp until sustained oscillation at Kp=7.0 (Ku), period Tu=12s",
             "Calculated ZN parameters: Kp=4.2, Ki=0.7, Kd=0.35",
             "Tested — overshoot was 3.8°C (acceptable but not ideal)",
             "Manual refinement: reduced Kp to 3.5, increased Kd to 0.25",
             "Final overshoot: 1.4°C, settling time: 38s"]),
        _p("Exported tuned parameters to Arduino EEPROM. Controller now boots with calibrated values."),
    ])

    run2_dry_b = _editor([
        _h("Run 2: Camera-Based Angle Detection Validation"),
        _p("Tested OpenCV angle measurement against manual protractor readings across 20 grip cycles."),
        _table(
            ["Cycle", "Camera (°)", "Manual (°)", "Error (°)"],
            [["1", "21.3", "22.0", "-0.7"],
             ["5", "20.8", "21.5", "-0.7"],
             ["10", "21.5", "22.0", "-0.5"],
             ["15", "19.8", "20.5", "-0.7"],
             ["20", "18.9", "20.0", "-1.1"]]),
        _p("Systematic underestimate of ~0.7° due to camera parallax. Acceptable for control purposes. "
           "Note: cycle 20 shows reduced bending — consistent with the 12% force degradation observed in wet lab testing."),
    ])

    # =========================================================================
    # PHASE 3 — Biocompatibility & System Benchmarking (Mar 2026)
    # =========================================================================

    exp3_wet = _editor([
        _h("Objective"),
        _p("Evaluate biocompatibility of the Formulation B hydrogel for potential medical/food-handling applications. "
           "Perform cytotoxicity assay (ISO 10993-5) and leachable analysis."),
        _h("Materials"),
        _ul(["Formulation B hydrogel samples (10mm discs, n=12)",
             "L929 mouse fibroblast cell line (ATCC CCL-1)",
             "DMEM + 10% FBS + 1% Pen/Strep",
             "MTT assay kit (Invitrogen V13154)",
             "96-well tissue culture plates",
             "ICP-MS for leachable metal analysis",
             "HPLC for residual monomer detection"]),
        _h("Protocol"),
        _ol(["Sterilize hydrogel samples by autoclaving (121°C, 20 min) — verify gel integrity post-autoclave",
             "Prepare extraction medium: place 3 gel discs in 10 mL DMEM, incubate 37°C for 24h and 72h",
             "Seed L929 cells at 10,000 cells/well in 96-well plates, culture 24h",
             "Replace medium with gel extract (100%, 50%, 25% dilutions) or fresh DMEM (positive control)",
             "Incubate 24h, then perform MTT assay",
             "Separately: soak 3 gel discs in DI water for 7 days, analyze leachate by ICP-MS and HPLC"]),
        _h("Results"),
        _p("Hydrogel passes ISO 10993-5 cytotoxicity criteria. Cell viability remains above 85% for all extract concentrations."),
        _table(
            ["Condition", "Cell viability (%)", "Pass (>70%)?"],
            [["Control (fresh DMEM)", "100 ± 3.2", "—"],
             ["24h extract, 100%", "91.3 ± 4.1", "PASS"],
             ["24h extract, 50%", "95.7 ± 2.8", "PASS"],
             ["72h extract, 100%", "85.4 ± 5.3", "PASS"],
             ["72h extract, 50%", "93.1 ± 3.6", "PASS"]]),
        _h("Leachable Analysis"),
        _table(
            ["Analyte", "Detected level", "Regulatory limit", "Status"],
            [["Residual NIPAAm monomer", "0.8 ppm", "<5 ppm", "PASS"],
             ["APS residue", "0.12 ppm", "<1 ppm", "PASS"],
             ["Heavy metals (total)", "<0.05 ppm", "<1 ppm", "PASS"]]),
        _h("Conclusions"),
        _p("Formulation B hydrogel is biocompatible per ISO 10993-5 standards. Safe for skin-contact and food-handling applications. "
           "Autoclave sterilization did not degrade gel properties (swelling ratio within 5% of pre-autoclave values). "
           "Ready for regulatory submission if pursuing medical device classification."),
    ])

    exp3_dry = _editor([
        _h("Objective"),
        _p("Benchmark the complete gripper system against performance targets. Run standardized pick-and-place tests "
           "and compare to commercial soft grippers."),
        _h("Test Setup"),
        _ul(["Gripper mounted on UR5e robot arm (fixed Z-height above test platform)",
             "10 standardized test objects (ISO soft gripper benchmark set)",
             "Force/torque sensor (ATI Nano17) at wrist for grip force measurement",
             "Thermal camera (FLIR A300) for temperature field visualization",
             "High-speed camera (Chronos 2.1) for deformation dynamics"]),
        _h("Benchmark Protocol"),
        _ol(["Pick each object from flat surface, lift 50mm, hold 10s, place at target location 100mm away",
             "Record: success/fail, grip force, cycle time, object deformation",
             "Repeat 10 trials per object (100 total picks)",
             "Compare to Soft Robotics mGrip (commercial pneumatic gripper)"]),
        _h("Results Summary"),
        _table(
            ["Object", "Our gripper (success %)", "mGrip (success %)", "Our grip force (N)", "mGrip force (N)"],
            [["Foam cube 20mm", "98%", "100%", "0.14", "0.85"],
             ["Rubber ball 15mm", "87%", "95%", "0.11", "0.62"],
             ["Egg (raw)", "72%", "90%", "0.09", "0.31"],
             ["Strawberry", "90%", "85%", "0.12", "0.45"],
             ["Glass vial 12mm", "45%", "92%", "0.06", "0.71"],
             ["Fabric swatch", "95%", "70%", "0.13", "0.22"]]),
        _h("Analysis"),
        _p("Our gripper excels at delicate/deformable objects (strawberry: 90% vs 85%, fabric: 95% vs 70%) due to conformable surface and gentle force. "
           "Significantly weaker on rigid smooth objects (glass vial: 45% vs 92%) — confirms the texture limitation identified in Phase 2. "
           "Cycle time is our main weakness: 180s vs 2s for the pneumatic mGrip."),
        _h("Power Consumption"),
        _table(
            ["Phase", "Our gripper (W)", "mGrip (W)"],
            [["Closing", "4.2", "12.0 (compressor)"],
             ["Holding", "1.8", "0.3 (valve hold)"],
             ["Opening", "0 (passive)", "8.0 (vacuum release)"],
             ["Avg per cycle", "2.1", "6.8"]]),
        _p("Our gripper uses 69% less energy per cycle despite slower operation — advantageous for battery-powered mobile robots."),
        _h("Conclusions"),
        _p("The bio-inspired hydrogel gripper occupies a distinct niche: low-force, delicate object handling with excellent energy efficiency. "
           "Not suitable as a general-purpose gripper (too slow, weak on rigid objects). "
           "Recommended applications: agricultural harvesting, lab sample handling, food packaging. "
           "Key improvements needed: (1) surface texturing for smooth objects, (2) active cooling for faster cycling, "
           "(3) nanoclay reinforcement for longer fatigue life."),
    ])

    run3_wet_a = _editor([
        _h("Run 1: Autoclave Integrity Test"),
        _p("Autoclaved 6 hydrogel discs at 121°C for 20 min. Compared properties to non-autoclaved controls."),
        _table(
            ["Property", "Pre-autoclave", "Post-autoclave", "Change"],
            [["Swelling ratio", "12.3 ± 0.4", "11.8 ± 0.6", "-4.1%"],
             ["Young's modulus (kPa)", "15.8 ± 1.2", "16.4 ± 1.5", "+3.8%"],
             ["Deswelling time (s)", "90 ± 8", "95 ± 10", "+5.6%"],
             ["Visual appearance", "Translucent", "Slightly yellowed", "Cosmetic only"]]),
        _p("All changes within acceptable limits. Autoclave sterilization validated for this hydrogel."),
    ])

    run3_wet_b = _editor([
        _h("Run 2: Cytotoxicity Assay — Full Dataset"),
        _p("Ran MTT assay in triplicate with 24h and 72h extraction time points."),
        _h("Raw Absorbance Data (570nm)"),
        _table(
            ["Condition", "Rep 1", "Rep 2", "Rep 3", "Mean ± SD"],
            [["Control", "1.82", "1.75", "1.79", "1.79 ± 0.04"],
             ["24h 100%", "1.68", "1.59", "1.63", "1.63 ± 0.05"],
             ["24h 50%", "1.73", "1.70", "1.71", "1.71 ± 0.02"],
             ["72h 100%", "1.56", "1.48", "1.54", "1.53 ± 0.04"],
             ["72h 50%", "1.69", "1.64", "1.67", "1.67 ± 0.03"]]),
        _p("Cell morphology normal under microscopy for all conditions — no rounding, detachment, or granularity observed. "
           "72h 100% extract shows lowest viability (85.4%) but still well above the 70% threshold."),
    ])

    run3_dry_a = _editor([
        _h("Run 1: Object-by-Object Breakdown"),
        _p("Detailed analysis of the 100-pick benchmark test. Failure modes categorized."),
        _h("Failure Analysis"),
        _table(
            ["Object", "Failures (of 10)", "Primary failure mode"],
            [["Foam cube", "0", "—"],
             ["Rubber ball", "1", "Slip during lift (insufficient friction)"],
             ["Egg", "3", "2x slip, 1x cracked (over-force)"],
             ["Strawberry", "1", "Stem caught on finger edge"],
             ["Glass vial", "6", "All slips — surface too smooth"],
             ["Fabric swatch", "0", "—"]]),
        _p("Glass vial failures are systematic — the smooth cylindrical surface provides no friction anchor points. "
           "Egg crack occurred because the outer finger contacted the egg equator with concentrated force. "
           "Recommended: add silicone micro-bumps (0.5mm height, 2mm pitch) to finger contact surface."),
    ])

    run3_dry_b = _editor([
        _h("Run 2: Thermal Camera Analysis"),
        _p("Used FLIR A300 to visualize temperature distribution during grip cycle. "
           "Key finding: significant thermal gradient along finger length."),
        _h("Temperature Distribution at t=45s (grip closed)"),
        _table(
            ["Position", "Temperature (°C)"],
            [["Wire region (mid-finger)", "42.1"],
             ["Finger tip", "35.8"],
             ["Finger base", "38.2"],
             ["Surrounding water (5mm away)", "26.3"]]),
        _p("The 6.3°C gradient from wire to tip means the tip actuates less than the mid-section. "
           "This actually helps gripping — the tip conforms to objects while the mid-section provides bending force. "
           "However, it also means the tip has less grip force, explaining some of the slip failures."),
        _p("Thermal recovery mapping shows full cool-down takes 110s, but the finger returns to functional "
           "(open) state at 90s when tip temperature drops below 30°C."),
    ])

    # =========================================================================
    # Insert all data into the database
    # =========================================================================

    # Dates for chronological consistency
    dates = [
        "2026-01-15T10:00:00+03:00",  # Phase 1 experiments
        "2026-01-18T14:00:00+03:00",  # Phase 1 runs batch 1
        "2026-01-22T09:00:00+03:00",  # Phase 1 runs batch 2
        "2026-02-05T10:00:00+03:00",  # Phase 2 experiments
        "2026-02-10T11:00:00+03:00",  # Phase 2 runs batch 1
        "2026-02-18T15:00:00+03:00",  # Phase 2 runs batch 2
        "2026-03-01T10:00:00+03:00",  # Phase 3 experiments
        "2026-03-03T09:00:00+03:00",  # Phase 3 runs batch 1
        "2026-03-05T16:00:00+03:00",  # Phase 3 runs batch 2
    ]

    experiments = [
        ("Hydrogel Synthesis & Characterization", "wet", exp1_wet, dates[0], ["hydrogel", "phase-1"]),
        ("FEA Simulation of Gripper Geometry", "dry", exp1_dry, dates[0], ["simulation", "phase-1"]),
        ("Gripper Prototype Fabrication & Testing", "wet", exp2_wet, dates[3], ["fabrication", "hydrogel", "phase-2"]),
        ("Closed-Loop Temperature Controller", "dry", exp2_dry, dates[3], ["control", "simulation", "phase-2"]),
        ("Biocompatibility Assessment (ISO 10993-5)", "wet", exp3_wet, dates[6], ["biocompat", "hydrogel", "phase-3"]),
        ("System Benchmark vs Commercial Grippers", "dry", exp3_dry, dates[6], ["benchmark", "control", "phase-3"]),
    ]

    runs_data = [
        # (experiment_index, title, content, date)
        (0, "Initial Synthesis Batch", run1_wet_a, dates[1]),
        (0, "Thermal Response Characterization", run1_wet_b, dates[2]),
        (1, "Mesh Convergence Study", run1_dry_a, dates[1]),
        (1, "Radial vs Bilayer Comparison", run1_dry_b, dates[2]),
        (2, "PDMS Backing Fabrication", run2_wet_a, dates[4]),
        (2, "Gripper Assembly and First Grip Tests", run2_wet_b, dates[5]),
        (3, "PID Tuning Session", run2_dry_a, dates[4]),
        (3, "Camera-Based Angle Detection Validation", run2_dry_b, dates[5]),
        (4, "Autoclave Integrity Test", run3_wet_a, dates[7]),
        (4, "Cytotoxicity Assay — Full Dataset", run3_wet_b, dates[8]),
        (5, "Object-by-Object Breakdown", run3_dry_a, dates[7]),
        (5, "Thermal Camera Analysis", run3_dry_b, dates[8]),
    ]

    exp_ids = []
    with get_db() as db:
        for title, lab, content, date, tags in experiments:
            cur = db.execute("""
                INSERT INTO experiments (title, lab, content_json, created_at)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (title, lab, content, date))
            eid = cur.fetchone()["id"]
            exp_ids.append(eid)
            for tag_name in tags:
                db.execute("""
                    INSERT INTO entity_tags (entity_type, entity_id, tag_id)
                    VALUES ('experiment', %s, %s) ON CONFLICT DO NOTHING
                """, (eid, tag_ids[tag_name]))
            db.execute("""
                INSERT INTO activity_log (entity_type, entity_id, entity_title, action, created_at)
                VALUES ('experiment', %s, %s, 'created', %s)
            """, (eid, title, date))

        for exp_idx, title, content, date in runs_data:
            cur = db.execute("""
                INSERT INTO runs (experiment_id, title, content_json, created_at)
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (exp_ids[exp_idx], title, content, date))
            rid = cur.fetchone()["id"]
            db.execute("""
                INSERT INTO activity_log (entity_type, entity_id, entity_title, action, created_at)
                VALUES ('run', %s, %s, 'created', %s)
            """, (rid, title, date))

    print(f"Seeded {len(experiments)} experiments with {len(runs_data)} runs and {len(tag_defs)} tags.")


def clean_db():
    """Remove all user data but keep schema."""
    tables = [
        "chat_messages", "activity_log", "entity_tags",
        "attachments", "experiment_attachments", "media",
        "runs", "concept_steps", "concept_notes",
        "experiments", "concepts", "tags",
    ]
    with get_db() as db:
        for t in tables:
            db.execute(f"DELETE FROM {t}")
    print("Database cleaned.")


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv:
        if "--clean" in sys.argv:
            clean_db()
        seed_mock_data()
    elif "--clean" in sys.argv:
        clean_db()
    else:
        app.run(host="127.0.0.1", port=5001, debug=True)
