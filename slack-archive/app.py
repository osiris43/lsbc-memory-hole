import sqlite3
import os
import re
import json
import logging
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.path.join(os.path.dirname(__file__), 'archive.db')
SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN')
SLACK_SIGNING_SECRET = os.environ.get('SLACK_SIGNING_SECRET')

logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def parse_tags(raw: str) -> str:
    """Normalize a raw tag string like '#AI, food, #Funny' → 'ai food funny'."""
    parts = re.split(r'[\s,]+', raw.strip())
    seen, result = set(), []
    for part in parts:
        t = part.lstrip('#').lower()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return ' '.join(result)


def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            title             TEXT NOT NULL,
            url               TEXT,
            notes             TEXT,
            category          TEXT,
            source            TEXT,
            saved_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            content_date      TEXT,
            tags              TEXT,
            slack_message_ts  TEXT,
            slack_channel_id  TEXT,
            slack_author_id   TEXT
        )
    """)
    for col in ('tags', 'slack_message_ts', 'slack_channel_id', 'slack_author_id'):
        try:
            db.execute(f"ALTER TABLE entries ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    db.commit()


@app.before_request
def before_request():
    init_db()


def get_categories():
    return [
        row[0] for row in
        get_db().execute(
            "SELECT DISTINCT category FROM entries "
            "WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
    ]


def create_entry(*, title, url=None, notes=None, category=None, source=None,
                 content_date=None, tags=None,
                 slack_message_ts=None, slack_channel_id=None, slack_author_id=None):
    """Insert one entry and commit. Must be called within a Flask app context."""
    db = get_db()
    db.execute(
        """INSERT INTO entries
           (title, url, notes, category, source, content_date, tags,
            slack_message_ts, slack_channel_id, slack_author_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, url, notes, category, source, content_date, tags,
         slack_message_ts, slack_channel_id, slack_author_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    db = get_db()
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()
    tag = request.args.get('tag', '').strip().lstrip('#').lower()

    query = "SELECT * FROM entries"
    params = []
    conditions = []

    if q:
        conditions.append("(title LIKE ? OR notes LIKE ? OR url LIKE ? OR tags LIKE ?)")
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%'])

    if cat:
        conditions.append("category = ?")
        params.append(cat)

    if tag:
        conditions.append("(' ' || COALESCE(tags, '') || ' ') LIKE ?")
        params.append(f'% {tag} %')

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY saved_at DESC"

    entries = db.execute(query, params).fetchall()
    categories = get_categories()

    all_tags_raw = db.execute(
        "SELECT tags FROM entries WHERE tags IS NOT NULL AND tags != ''"
    ).fetchall()
    tag_counts: dict = {}
    for row in all_tags_raw:
        for t in row[0].split():
            tag_counts[t] = tag_counts.get(t, 0) + 1
    all_tags = sorted(tag_counts.keys())

    return render_template('index.html', entries=entries, categories=categories,
                           q=q, active_cat=cat, active_tag=tag, all_tags=all_tags)


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            return render_template('add.html', categories=get_categories(),
                                   error="Title is required.", form=request.form)

        raw_tags = request.form.get('tags', '').strip()
        create_entry(
            title=title,
            url=request.form.get('url', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
            category=request.form.get('category', '').strip() or None,
            source=request.form.get('source', '').strip() or None,
            content_date=request.form.get('content_date', '').strip() or None,
            tags=parse_tags(raw_tags) if raw_tags else None,
        )
        return redirect(url_for('index'))

    return render_template('add.html', categories=get_categories(), error=None, form={})


@app.route('/delete/<int:entry_id>', methods=['POST'])
def delete(entry_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Slack integration (only wired up when env vars are present)
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORIES = ['AI', 'Food', 'General', 'Other']

if SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET:
    from slack_bolt import App as BoltApp
    from slack_bolt.adapter.flask import SlackRequestHandler

    bolt_app = BoltApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
    slack_handler = SlackRequestHandler(bolt_app)

    def _category_options():
        """Return Block Kit option objects for the category dropdown."""
        with app.app_context():
            cats = get_categories() or _DEFAULT_CATEGORIES
        return [
            {"text": {"type": "plain_text", "text": c}, "value": c}
            for c in cats
        ]

    @bolt_app.shortcut("memory_hole_message")
    def handle_shortcut(shortcut, ack, client):
        ack()
        message = shortcut['message']
        raw_text = message.get('text', '')
        preview = raw_text[:500] + ('…' if len(raw_text) > 500 else '')
        channel_id = shortcut['channel']['id']

        meta = json.dumps({
            "channel_id": channel_id,
            "message_ts": message.get('ts', ''),
            "author_id": message.get('user', ''),
            "fallback_text": raw_text[:500],
        })

        client.views_open(
            trigger_id=shortcut['trigger_id'],
            view={
                "type": "modal",
                "callback_id": "archive_submit",
                "private_metadata": meta,
                "title": {"type": "plain_text", "text": "Archive Message"},
                "submit": {"type": "plain_text", "text": "Archive"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Message preview:*\n{preview}",
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "category_block",
                        "optional": True,
                        "label": {"type": "plain_text", "text": "Category"},
                        "hint": {"type": "plain_text", "text": "Pick an existing category, or leave blank and type a new one below."},
                        "element": {
                            "type": "static_select",
                            "action_id": "category",
                            "placeholder": {"type": "plain_text", "text": "Select a category"},
                            "options": _category_options(),
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "new_category_block",
                        "optional": True,
                        "label": {"type": "plain_text", "text": "New category"},
                        "hint": {"type": "plain_text", "text": "Type here to create a new category. Overrides the dropdown above."},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "new_category",
                            "placeholder": {"type": "plain_text", "text": "e.g. Politics"},
                        },
                    },
                    {
                        "type": "input",
                        "block_id": "tags_block",
                        "optional": True,
                        "label": {"type": "plain_text", "text": "Tags"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "tags",
                            "placeholder": {"type": "plain_text", "text": "#ai, food, #funny"},
                        },
                    },
                ],
            },
        )

    @bolt_app.view("archive_submit")
    def handle_submission(ack, body, client, view):
        meta = json.loads(view['private_metadata'])
        channel_id = meta['channel_id']
        message_ts = meta['message_ts']
        author_id = meta['author_id']
        fallback_text = meta['fallback_text']

        values = view['state']['values']
        new_cat = (values['new_category_block']['new_category'].get('value') or '').strip()
        existing_cat = (values['category_block']['category'].get('selected_option') or {}).get('value', '')
        category = new_cat or existing_cat or None
        if not category:
            ack(response_action="errors",
                errors={"new_category_block": "Please select an existing category or type a new one."})
            return

        raw_tags = (values['tags_block']['tags'].get('value') or '').strip()
        tags = parse_tags(raw_tags) if raw_tags else None
        submitting_user = body['user']['id']

        # Fetch authoritative message text; fall back to shortcut payload on error
        try:
            result = client.conversations_history(
                channel=channel_id, latest=message_ts, inclusive=True, limit=1
            )
            messages = result.get('messages', [])
            full_text = messages[0].get('text', fallback_text) if messages else fallback_text
        except Exception as e:
            logger.warning("conversations_history failed, using fallback text: %s", e)
            full_text = fallback_text

        title = full_text[:200]
        notes = full_text if len(full_text) > 200 else None

        try:
            with app.app_context():
                create_entry(
                    title=title,
                    notes=notes,
                    category=category,
                    source=submitting_user,
                    tags=tags,
                    slack_message_ts=message_ts,
                    slack_channel_id=channel_id,
                    slack_author_id=author_id,
                )
        except Exception as e:
            logger.exception("Failed to archive Slack entry")
            ack(response_action="errors",
                errors={"category_block": f"Archive failed: {e}"})
            return

        ack()

        tag_str = f"  |  tags: {raw_tags}" if raw_tags else ""
        try:
            client.chat_postMessage(
                channel=submitting_user,
                text=f"Archived! Category: *{category}*{tag_str}",
            )
        except Exception as e:
            logger.warning("Failed to send confirmation DM: %s", e)

    @app.route('/slack/events', methods=['POST'])
    def slack_events():
        return slack_handler.handle(request)

else:
    logger.info(
        "SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET not set — Slack integration disabled."
    )


if __name__ == '__main__':
    app.run(debug=True, port=5055)
