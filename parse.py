"""
Parse NASA SBIR/STTR BAA topic PDFs into a CSV.
Each row = one topic. Columns are inferred from document structure.

Usage: python nasa_pdf_to_csv.py [directory]
Defaults to ./test_data. Output: topics.csv in the same directory.
"""

import sys
import re
import sqlite3
from pathlib import Path
import pdfplumber
from loguru import logger


# ── Patterns ────────────────────────────────────────────────────────────────

RE_PROGRAM  = re.compile(r"\b(SBIR|STTR)\s*$")
RE_TOPIC_ID = re.compile(r"^([A-Z]+\.\d+\.[A-Z0-9]+):\s*(.*)$")
RE_SECTION  = re.compile(r"^([A-Z][A-Za-z &/()]+):$")
RE_KV       = re.compile(
    r"^(Lead Center|Participating Center\(s\)"
    r"|Expected TRL or TRL Range at completion of the Project"
    r"|Need Horizon):\s*(.+)$"
)
RE_NOISE    = re.compile(r"NASA SBIR/STTR Program|FY\d+-\d+ BAA Appendix|^\s*\d+\s*$")


# ── CSV columns ──────────────────────────────────────────────────────────────

COLUMNS = [
    "program",
    "topic_id",
    "title",
    "lead_center",
    "participating_centers",
    "trl_range",
    "need_horizon",
    "subtopic_description",
    "scope_and_objectives",
    "phase_i_deliverables",
    "phase_ii_deliverables",
    "phase_ii_deliverable_types",
    "state_of_the_art",
    "critical_gaps",
    "shortfalls_and_decadal_surveys",
    "references",
]

SECTION_MAP = {
    "subtopic problem statement/description": "subtopic_description",
    "scope and objectives":                   "scope_and_objectives",
    "desired deliverables of phase i":        "phase_i_deliverables",
    "phase i goals":                          "phase_i_deliverables",
    "phase i deliverables":                   "phase_i_deliverables",
    "desired deliverables of phase ii":       "phase_ii_deliverables",
    "phase ii goals":                         "phase_ii_deliverables",
    "phase ii deliverables":                  "phase_ii_deliverables",
    "desired deliverable types of phase ii":  "phase_ii_deliverable_types",
    "state of the art":                       "state_of_the_art",
    "critical gaps":                          "critical_gaps",
    "shortfalls and decadal surveys":         "shortfalls_and_decadal_surveys",
    "references":                             "references",
    # captured but not written to a column
    "primary technology taxonomy":            None,
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_lines(pdf_path: Path) -> list:
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            lines.extend(text.splitlines())
    return lines


def detect_program(lines: list) -> str:
    for line in lines[:10]:
        m = RE_PROGRAM.search(line.strip())
        if m:
            return m.group(1)
    return ""


def is_noise(line: str) -> bool:
    return bool(RE_NOISE.search(line))


def normalize(text: str) -> str:
    """Collapse internal whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def join_title(existing: str, fragment: str) -> str:
    """
    Append a title continuation fragment, handling PDF hard-hyphen line breaks.
    If existing ends with '-', it was a mid-word break: join directly.
    Otherwise insert a space.
    """
    if existing.endswith("-"):
        return existing + fragment
    return existing + " " + fragment


# ── Parser ───────────────────────────────────────────────────────────────────

def split_topics(lines: list, program: str) -> list:
    topics = []
    topic = None
    current_col = None      # CSV column currently accumulating
    section_buf = []        # lines for current section

    def flush():
        if topic is not None and current_col and section_buf:
            blob = normalize(" ".join(section_buf))
            if blob:
                prev = topic.get(current_col, "")
                topic[current_col] = (prev + " " + blob).strip() if prev else blob
        section_buf.clear()

    def start_topic(tid, raw_title):
        nonlocal topic, current_col
        flush()
        if topic:
            topics.append(topic)
        topic = {c: "" for c in COLUMNS}
        topic["program"] = program
        topic["topic_id"] = tid
        topic["title"] = normalize(raw_title)
        current_col = None
        section_buf.clear()

    title_open = False   # True while title is still wrapping

    for raw in lines:
        if is_noise(raw):
            continue

        line    = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            if section_buf:
                section_buf.append("")
            continue

        # ── Topic ID ─────────────────────────────────────────────────────
        m = RE_TOPIC_ID.match(stripped)
        if m:
            start_topic(m.group(1), m.group(2))
            # Title is open if the fragment doesn't yet close with ")"
            title_open = not m.group(2).strip().endswith(")")
            continue

        if topic is None:
            continue

        # ── Title continuation ────────────────────────────────────────────
        if title_open:
            if not RE_KV.match(stripped) and not RE_SECTION.match(stripped):
                topic["title"] = normalize(join_title(topic["title"], stripped))
                if stripped.endswith(")"):
                    title_open = False
                continue
            title_open = False

        # ── Inline key-value fields ───────────────────────────────────────
        m = RE_KV.match(stripped)
        if m:
            flush()
            current_col = None
            key, val = m.group(1).lower(), m.group(2).strip()
            if "lead center" in key:
                topic["lead_center"] = val
            elif "participating" in key:
                topic["participating_centers"] = val
            elif "trl" in key:
                topic["trl_range"] = val
            elif "need horizon" in key:
                topic["need_horizon"] = val
            continue

        # ── Section header ────────────────────────────────────────────────
        m = RE_SECTION.match(stripped)
        if m:
            flush()
            current_col = SECTION_MAP.get(m.group(1).lower())
            continue

        # ── Body content ──────────────────────────────────────────────────
        if current_col:
            section_buf.append(re.sub(r"^[•\-\*]\s+", "", stripped))

    flush()
    if topic:
        topics.append(topic)

    return topics


def parse_pdf(pdf_path: Path) -> list:
    lines = extract_lines(pdf_path)
    program = detect_program(lines)
    return split_topics(lines, program)


def main():
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data"
    if not directory.is_dir():
        logger.error(f"Directory not found: {directory}")
        sys.exit(1)

    pdfs = sorted(directory.glob("*.pdf")) + sorted(directory.glob("*.PDF"))
    if not pdfs:
        logger.error(f"No PDF files found in {directory}")
        sys.exit(1)

    all_topics = []
    for pdf in pdfs:
        topics = parse_pdf(pdf)
        logger.info(f"{pdf.name}: {len(topics)} topic(s)")
        all_topics.extend(topics)

    out = (directory / "topics.db").resolve()
    con = sqlite3.connect(out)
    col_defs = ", ".join(f'"{c}" TEXT' for c in COLUMNS)
    con.execute(f"CREATE TABLE IF NOT EXISTS topics ({col_defs})")
    con.execute("DELETE FROM topics")
    con.executemany(f"INSERT INTO topics VALUES ({', '.join('?' * len(COLUMNS))})",
                    [[t[c] for c in COLUMNS] for t in all_topics])
    con.commit()
    con.close()

    logger.success(f"→ {out} ({len(all_topics)} rows)")


if __name__ == "__main__":
    main()