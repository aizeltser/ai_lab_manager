# AI Lab Manager

A collaborative Electronic Lab Notebook (ELN) designed for multidisciplinary research teams. Built to manage scientific experiments, protocols, and research concepts, it features content editing and AI assistance, hierarchical page organization, and robust team collaboration tools. Engineered specifically for complex lab workflows, it provides a unified workspace where wet lab researchers, bioinformaticians, sensor engineers, and DevOps specialists can seamlessly drive shared projects forward.

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Opens at **http://127.0.0.1:5001**. No build step, no external database — everything runs from a single SQLite file (`eln.db`) created automatically on first launch.

## Stack

- **Backend:** Python / Flask (single-file `app.py`)
- **Database:** SQLite with raw SQL (no ORM)
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
- Shared AI prompt pane below both panels — saves to both experiments

### Duplicate Pages
- One-click duplication for experiments and concepts
- Copies content, tags, and parent assignment
- New page titled "Copy of [original]"

### AI Prompt Integration
- Designed as a foundation for future LLM integration

### Legacy Support
- Existing data (plain-text descriptions, setup tables, step-by-step instructions, file attachments) renders correctly via fallback templates
- Automatic one-time migration of legacy content to Editor.js JSON format

## Project Structure

```
ai_lab_manager/
  app.py                  # Flask application (all routes, DB schema, helpers)
  requirements.txt        # Flask + Werkzeug
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
  uploads/                # File uploads (gitignored)
  eln.db                  # SQLite database (gitignored, auto-created)
```

## Data Model

```
experiments (id, title, lab, content_json, parent_type, parent_id, ...)
  -> runs (id, experiment_id, title, content_json, ...)
       -> attachments (id, run_id, stored_name, original_name, ...)
       -> run_ai_prompts (run_id, text, ...)
  -> experiment_attachments (id, experiment_id, ...)
  -> experiment_ai_prompts (experiment_id, text, ...)

concepts (id, title, author, content_json, parent_type, parent_id, ...)
  -> concept_steps (id, concept_id, step_order, text, ...)  [legacy]
  -> concept_notes (concept_id, text, ...)                   [legacy]

tags (id, name, color)
entity_tags (entity_type, entity_id, tag_id)
activity_log (id, entity_type, entity_id, entity_title, action, created_at)
media (id, stored_name, original_name, entity_type, entity_id, ...)
```

All tables are created automatically on first request. Schema migrations run idempotently via `ALTER TABLE ADD COLUMN` with `PRAGMA table_info` checks. Foreign keys use `ON DELETE CASCADE`.
