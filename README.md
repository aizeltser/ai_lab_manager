# AI Lab Manager

A collaborative Electronic Lab Notebook (ELN) designed for multidisciplinary research teams. Built to manage scientific experiments, protocols, and research concepts, it features content editing, an AI assistant powered by Groq, hierarchical page organization, and robust team collaboration tools. Engineered specifically for complex lab workflows, it provides a unified workspace where wet lab researchers, bioinformaticians, sensor engineers, and DevOps specialists can seamlessly drive shared projects forward.

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Opens at **http://127.0.0.1:5001**.

### Prerequisites

- **PostgreSQL 16+** with the `citext` extension
- **Python 3.10+**
- **Groq API key** (free tier) — get one at [console.groq.com](https://console.groq.com)

```bash
# First-time setup: create database and user (once per machine)
sudo -u postgres psql -c "CREATE USER <user> WITH PASSWORD '<password>';"
sudo -u postgres psql -c "CREATE DATABASE eln_db OWNER <user>;"
sudo -u postgres psql -d eln_db -c "CREATE EXTENSION IF NOT EXISTS citext;"

# Configure connection and API key
cp .env.example .env   # then edit DATABASE_URL and GROQ_API_KEY
```

All tables are created automatically on first launch — no manual schema setup needed.

### Seed Demo Data

The app ships with a built-in mock dataset — a multi-phase robotics research project with 6 experiments, 12 runs, and 9 tags - for testing the AI assistant and exploring the UI.

```bash
python app.py --seed              # seed only if database is empty
python app.py --clean --seed      # wipe all data and reseed from scratch
python app.py --clean             # wipe all data without reseeding
```

## Stack

- **Backend:** Python / Flask (single-file `app.py`)
- **Database:** PostgreSQL with raw SQL via psycopg3 (no ORM), connection pooling via psycopg_pool
- **AI:** Groq API (Llama 3.3 70B) — free tier, OpenAI-compatible chat completions
- **Frontend:** Jinja2 templates, vanilla JS, single CSS file
- **Editor:** [Editor.js](https://editorjs.io/) (WYSIWYG block editor loaded via CDN)

## Features

### Content Editing
- Block-based WYSIWYG editor (Editor.js) with 12 plugins
- Text formatting, headings, ordered/unordered lists (with nesting), tables
- Inline images and file attachments with drag-and-drop upload
- Code blocks, quotes, checklists, delimiters, inline code, highlights
- Instant block deletion (no two-click confirmation)

### Page Organization
- **Experiments** — assigned to Wet Lab or Dry Lab groups
- **Concepts** — wiki pages for protocols, meeting notes, documentation
- **Runs** — child pages under experiments for individual trial records
- **Unified tree hierarchy** — any page can be a child of any other page (experiments and concepts nest freely)
- **Breadcrumb navigation** — ancestor-aware trail on every page

### Page Templates
Three built-in templates to quick-start new pages:
- **Wet Lab Protocol** — objective, materials, protocol steps, setup table, results, conclusions
- **Bioinformatics Pipeline** — overview, input data, tools, pipeline steps, parameters, output
- **Meeting Notes** — details table, agenda, discussion notes, action items checklist

### Tags & Labels
- Color-coded tags (8 colors: red, amber, green, blue, purple, pink, gray, teal)
- Inline tag management on any page — add new or pick existing tags
- Tag filtering on experiment and concept list pages
- Tags shown in sidebar for quick navigation

### Activity Log
- Automatic tracking of all create, edit, delete, and duplicate actions
- Recent activity timeline on the home page

### Split-View Comparison
- Side-by-side comparison of two experiments
- Ctrl+click (or Cmd+click) two experiments in the sidebar to open compare view
- AI chat available below both panels

### Duplicate Pages
- One-click duplication for experiments and concepts
- Copies content, tags, and parent assignment
- New page titled "Copy of [original]"

### AI Assistant
- Chat-based AI assistant on every experiment, run, and concept page
- Powered by Groq (Llama 3.3 70B) — free API tier, no credit card required
- Full project context injected automatically: the AI sees all experiments, runs, concepts, tags, and recent activity
- Entity-aware: when chatting from a specific page, that entity's content is prioritized
- Multi-turn conversation with persistent chat history per entity
- Ask questions like "What formulation had the fastest response time?" or "Compare Phase 1 and Phase 2 results"

### Legacy Support
- Existing data (plain-text descriptions, setup tables, step-by-step instructions, file attachments) renders correctly via fallback templates
- Automatic one-time migration of legacy content to Editor.js JSON format

## Project Structure

```
ai_lab_manager/
  app.py                  # Flask application (all routes, DB schema, helpers)
  .env                    # DATABASE_URL + FLASK_SECRET_KEY (gitignored)
  requirements.txt        # Flask, Werkzeug, psycopg3, psycopg_pool, python-dotenv
  CLAUDE.md               # Project conventions for AI assistants
  static/
    styles.css            # All styles (single file)
  templates/
    base.html             # App shell: sidebar, topbar, breadcrumbs
    index.html            # Home page: experiment list + activity log
    concepts.html         # Concepts list page
    experiment.html       # Experiment detail view
    experiment_new.html   # New experiment form (with templates)
    experiment_edit.html  # Edit experiment form
    concept_view.html     # Concept detail view
    concept_new.html      # New concept form (with templates)
    concept_edit.html     # Edit concept form
    run_view.html         # Run detail view
    run_new.html          # New run form
    run_edit.html         # Edit run form
    compare.html          # Split-view comparison page
    _editor.html          # Editor.js macros (CDN loading, init, form serialize)
    _render_blocks.html   # Server-side rendering of Editor.js JSON blocks
    _tags_inline.html     # Inline tag management partial
    _ai_chat.html         # AI chat panel partial (vanilla JS)
  uploads/                # File uploads (gitignored)
```

## Data Model

```
experiments (id, title, lab, content_json, parent_type, parent_id, ...)
  -> runs (id, experiment_id, title, content_json, ...)
       -> attachments (id, run_id, stored_name, original_name, ...)
  -> experiment_attachments (id, experiment_id, ...)

concepts (id, title, author, content_json, parent_type, parent_id, ...)
  -> concept_steps (id, concept_id, step_order, text, ...)  [legacy]
  -> concept_notes (concept_id, text, ...)                   [legacy]

tags (id, name, color)
entity_tags (entity_type, entity_id, tag_id)
activity_log (id, entity_type, entity_id, entity_title, action, created_at)
media (id, stored_name, original_name, entity_type, entity_id, ...)
chat_messages (id, entity_type, entity_id, role, content, created_at)
```

All tables are created automatically at startup via `CREATE TABLE IF NOT EXISTS`. Foreign keys use `ON DELETE CASCADE`. Tags use `CITEXT` for case-insensitive uniqueness.
