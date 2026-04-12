import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, g
from datetime import datetime, timezone

DATABASE = os.path.join(os.path.dirname(__file__), 'archive.db')

app = Flask(__name__)


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


def init_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            url          TEXT,
            notes        TEXT,
            category     TEXT,
            source       TEXT,
            saved_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            content_date TEXT
        )
    """)
    db.commit()


@app.before_request
def before_request():
    init_db()


@app.route('/')
def index():
    db = get_db()
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '').strip()

    query = "SELECT * FROM entries"
    params = []
    conditions = []

    if q:
        conditions.append("(title LIKE ? OR notes LIKE ? OR url LIKE ?)")
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])

    if cat:
        conditions.append("category = ?")
        params.append(cat)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY saved_at DESC"

    entries = db.execute(query, params).fetchall()

    categories = [
        row[0] for row in
        db.execute("SELECT DISTINCT category FROM entries WHERE category IS NOT NULL AND category != '' ORDER BY category").fetchall()
    ]

    return render_template('index.html', entries=entries, categories=categories, q=q, active_cat=cat)


@app.route('/add', methods=['GET', 'POST'])
def add():
    db = get_db()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            categories = [
                row[0] for row in
                db.execute("SELECT DISTINCT category FROM entries WHERE category IS NOT NULL AND category != '' ORDER BY category").fetchall()
            ]
            return render_template('add.html', categories=categories, error="Title is required.", form=request.form)

        db.execute(
            "INSERT INTO entries (title, url, notes, category, source, content_date) VALUES (?, ?, ?, ?, ?, ?)",
            (
                title,
                request.form.get('url', '').strip() or None,
                request.form.get('notes', '').strip() or None,
                request.form.get('category', '').strip() or None,
                request.form.get('source', '').strip() or None,
                request.form.get('content_date', '').strip() or None,
            )
        )
        db.commit()
        return redirect(url_for('index'))

    categories = [
        row[0] for row in
        db.execute("SELECT DISTINCT category FROM entries WHERE category IS NOT NULL AND category != '' ORDER BY category").fetchall()
    ]
    return render_template('add.html', categories=categories, error=None, form={})


@app.route('/delete/<int:entry_id>', methods=['POST'])
def delete(entry_id):
    db = get_db()
    db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    db.commit()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=5055)
