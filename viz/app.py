import sqlite3
import os
import sys
from flask import Flask, render_template, request, jsonify
from loguru import logger

_HERE       = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.environ.get("DB_PATH",     os.path.join(_HERE, "..", "data", "topics.db"))
SCORES_PATH = os.environ.get("SCORES_PATH", os.path.join(_HERE, "..", "data", "scores.db"))
app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_scores():
    with sqlite3.connect(SCORES_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                topic_id TEXT PRIMARY KEY,
                score    INTEGER
            )
        """)


def query(sql, params=()):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_with_scores(sql, params=()):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(f"ATTACH DATABASE '{SCORES_PATH}' AS sdb")
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.route("/")
def index():
    filters = {
        "programs": [r["program"] for r in query("SELECT DISTINCT program FROM topics WHERE program IS NOT NULL ORDER BY program")],
    }
    return render_template("index.html", filters=filters)


@app.route("/api/topics")
def api_topics():
    q         = request.args.get("q", "").strip()
    program   = request.args.get("program", "")
    min_score = request.args.get("min_score", "")
    no_score  = request.args.get("no_score", "")

    where, params = ["1=1"], []
    if q:
        where.append("(t.topic_id LIKE ? OR t.title LIKE ? OR t.subtopic_description LIKE ? OR t.scope_and_objectives LIKE ?)")
        params += [f"%{q}%"] * 4
    if program:
        where.append("t.program = ?"); params.append(program)
    if no_score:
        where.append("s.score IS NULL")
    elif min_score != "":
        where.append("s.score >= ?"); params.append(int(min_score))

    sql = f"""
        SELECT t.topic_id, t.title, t.program, t.lead_center,
               t.participating_centers, t.trl_range, t.need_horizon,
               s.score, s.keywords, s.objective
        FROM topics t
        LEFT JOIN sdb.scores s ON s.topic_id = t.topic_id
        WHERE {" AND ".join(where)}
        ORDER BY t.topic_id
        LIMIT 500
    """
    return jsonify(query_with_scores(sql, params))


@app.route("/api/topic/<path:topic_id>")
def api_topic(topic_id):
    sql = """
        SELECT t.*, s.score, s.keywords, s.objective
        FROM topics t
        LEFT JOIN sdb.scores s ON s.topic_id = t.topic_id
        WHERE t.topic_id = ?
    """
    rows = query_with_scores(sql, (topic_id,))
    if not rows:
        return jsonify({}), 404
    return jsonify(rows[0])


@app.route("/api/topic/<path:topic_id>/score", methods=["POST"])
def set_score(topic_id):
    data = request.get_json()
    score = data.get("score")
    if score is not None and score not in range(1, 6):
        return jsonify({"error": "score must be 1-5"}), 400
    with sqlite3.connect(SCORES_PATH) as conn:
        if score is None:
            conn.execute("DELETE FROM scores WHERE topic_id = ?", (topic_id,))
        else:
            conn.execute(
                "INSERT INTO scores (topic_id, score) VALUES (?, ?) "
                "ON CONFLICT(topic_id) DO UPDATE SET score = excluded.score",
                (topic_id, score),
            )
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_scores()
    app.run(debug=True, port=5051)
