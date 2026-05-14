"""
Reads topics from data/topics.db, runs each through a local Ollama model to
extract keywords and a one-sentence objective, then writes results to
data/scores.db.

Usage:
    python extract.py [--model mistral-small:24b] [--force]

Options:
    --model   Ollama model to use (default: mistral-small:24b)
    --force   Re-run even for topics that already have keywords
"""

import argparse
import json
import sqlite3
from pathlib import Path

import ollama
from loguru import logger
from tqdm import tqdm

DATA = Path(__file__).parent / "data"
TOPICS_DB = DATA / "topics.db"
SCORES_DB = DATA / "scores.db"

PROMPT_TMPL = """\
You are analyzing a NASA SBIR solicitation topic. Return ONLY a valid JSON object with exactly two keys:
- "keywords": a list of 6-10 specific technical terms, technologies, or acronyms central to this topic
- "objective": 1-2 sentence concisely describing what NASA wants built or demonstrated

Topic title: {title}

Subtopic description:
{subtopic_description}

Scope and objectives:
{scope_and_objectives}

State of the art:
{state_of_the_art}

Critical gaps:
{critical_gaps}

Phase I deliverables:
{phase_i_deliverables}

Phase II deliverables:
{phase_ii_deliverables}

Return JSON only. No explanation, no markdown, no code fences."""


def build_prompt(row: dict) -> str:
    return PROMPT_TMPL.format(
        title=row["title"] or "",
        subtopic_description=row["subtopic_description"] or "",
        scope_and_objectives=row["scope_and_objectives"] or "",
        state_of_the_art=row["state_of_the_art"] or "",
        critical_gaps=row["critical_gaps"] or "",
        phase_i_deliverables=row["phase_i_deliverables"] or "",
        phase_ii_deliverables=row["phase_ii_deliverables"] or "",
    )


def parse_response(content: str) -> tuple[str, str]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    data = json.loads(content)
    keywords = data.get("keywords", [])
    if isinstance(keywords, list):
        keywords = ", ".join(keywords)
    objective = data.get("objective", "")
    return keywords.strip(), objective.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="mistral-small:24b")
    parser.add_argument("--force", action="store_true", help="re-run topics that already have keywords")
    args = parser.parse_args()

    topics_con = sqlite3.connect(TOPICS_DB)
    topics_con.row_factory = sqlite3.Row
    topics = [dict(r) for r in topics_con.execute(
        "SELECT topic_id, title, subtopic_description, scope_and_objectives, state_of_the_art, critical_gaps, phase_i_deliverables, phase_ii_deliverables FROM topics"
    ).fetchall()]
    topics_con.close()

    scores_con = sqlite3.connect(SCORES_DB)
    scores_con.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            topic_id  TEXT PRIMARY KEY,
            score     INTEGER,
            keywords  TEXT,
            objective TEXT
        )
    """)
    scores_con.commit()

    if not args.force:
        done = {r[0] for r in scores_con.execute(
            "SELECT topic_id FROM scores WHERE keywords IS NOT NULL"
        ).fetchall()}
        topics = [t for t in topics if t["topic_id"] not in done]

    if not topics:
        logger.info("All topics already enriched. Use --force to re-run.")
        return

    logger.info(f"Extracting Objective and Keywords from {len(topics)} topics with model {args.model}")
    client = ollama.Client()

    for topic in tqdm(topics, unit="topic"):
        tid = topic["topic_id"]
        try:
            prompt = build_prompt(topic)
            logger.debug(f"\n--- prompt for {tid} ---\n{prompt}\n---")
            result = client.chat(
                model=args.model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            keywords, objective = parse_response(result.message.content)
            scores_con.execute("""
                INSERT INTO scores (topic_id, keywords, objective)
                VALUES (?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    keywords  = excluded.keywords,
                    objective = excluded.objective
            """, (tid, keywords, objective))
            scores_con.commit()
            logger.debug(f"{tid}: {keywords[:60]}…")
        except Exception as e:
            logger.error(f"{tid}: {e}")

    scores_con.close()
    logger.success(f"Done. {len(topics)} topics enriched.")


if __name__ == "__main__":
    main()
