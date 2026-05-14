# NASA SBIR Topic Browser

NASA releases SBIR/STTR Phase I solicitations as long PDFs with no single objective statement or per-topic keywords.

This tool parses the PDFs into a database, runs each topic through a local LLM (Ollama) to generate keywords and a one-line objective, and serves a dashboard for browsing, filtering, scoring, and exporting.

**Data source:** https://www.nasa.gov/sbir_sttr/phase-i/

---

Download the BAA appendix PDFs, crop out the front-matter / instructions pages
so only the topic listings remain, and drop them in `./data` before running
the parser.

## Setup

### Install Python 3.13

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv
```

### Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Install dependencies

```bash
poetry install --without dev
```

## Workflow

### 1. Parse PDFs → topics.db

Place cropped PDFs in `./data`, then run:

```bash
poetry run python parse.py
```

Output: `data/topics.db` with one row per topic.

### 2. Enrich topics → scores.db

Requires [Ollama](https://ollama.com) running locally with a model pulled.

#### Install and start Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
```

Pull a model. Recommended options:

| | `mistral-small:24b` | `qwen2.5:32b-q4_K_M` | `llama3.1:8b` | `qwen2.5:7b` |
|---|---|---|---|---|
| RAM usage | ~15 GB | ~20 GB | ~5 GB | ~5 GB |
| JSON reliability | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★★★☆ |
| Instruction following | ★★★★☆ | ★★★★★ | ★★★☆☆ | ★★★★☆ |
| Speed (M4 Max) | ~15 tok/s | ~10 tok/s | ~60 tok/s | ~55 tok/s |
| Reasoning quality | ★★★★☆ | ★★★★★ | ★★★☆☆ | ★★★☆☆ |

```bash
ollama pull mistral-small:24b
```

```bash
poetry run python extract.py
# or to use a different model:
poetry run python extract.py --model llama3.1:8b
# re-run all topics (ignore already-enriched):
poetry run python extract.py --force
```

Output: `data/scores.db` with keywords and objective per topic.

### 3. Browse topics

```bash
poetry run python viz/app.py
```
