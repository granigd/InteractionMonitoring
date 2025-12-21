# InteractionMonitoring — Backend

> **Master Thesis Project** · TU Wien · Dominik Granig  
> *Monitoring and Analyzing User Interactions in GLSP-Based Modeling Tools*

---

## 📺 Showcase

> **▶ Watch the full demo on YouTube**
>
> [![YouTube Demo Placeholder](https://img.shields.io/badge/YouTube-Watch%20Demo-red?style=for-the-badge&logo=youtube)](https://youtube.com)
>
> `[ PLACEHOLDER ]`

---

## Overview

This repository contains the **backend server** developed as part of a master thesis at TU Wien. The thesis investigates how user interaction data collected from GLSP-based modeling tools can be systematically recorded, stored, and analyzed to identify usability problems and behavioral patterns.

The server is built with **FastAPI** and exposes a REST API that acts as the central data sink and analysis engine for one or more connected GLSP frontend tools (e.g. [bigUML](https://github.com/borkdominik/bigUML)). It handles the full lifecycle from raw event ingestion to high-level usability metrics and process-mining exports.

### Research Context

Graphical Language Server Protocol (GLSP) is an open-source framework for building diagram editors in web and IDE environments. While GLSP makes it easy to build feature-rich modeling tools, it provides no built-in instrumentation for studying how users actually interact with those editors. This thesis bridges that gap by:

1. Defining a **tool-agnostic interaction recording format** that any GLSP editor can adopt.
2. Building a **backend** (this repository) that persists interaction sessions and eye-tracking data.
3. Implementing **automated usability analysis** algorithms (friction detection, clickstream mining) directly in the backend.
4. Exporting data to **standard process-mining formats** (XES) for deeper analysis in external tools.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│           GLSP Frontend (e.g. bigUML VSCode)         │
│  Records clicks, creates, deletes, viewport changes  │
│                + optional eye-tracking data          │
└────────────────────────┬─────────────────────────────┘
                         │  HTTP  (JSON)
                         ▼
┌──────────────────────────────────────────────────────┐
│         InteractionMonitoring  (this repo)           │
│                                                      │
│   ┌─────────────┐          ┌─────────────────────┐   │
│   │  /sessions  │          │     /analysis       │   │
│   │             │          │                     │   │
│   │ • Upload    │          │ • Friction detect.  │   │
│   │ • List      │          │ • Clickstream / N-  │   │
│   │ • Filter    │          │   gram analysis     │   │
│   │ • Eye track │          │ • XES export        │   │
│   │ • Heatmaps  │          │ • Gaze heatmaps     │   │
│   └──────┬──────┘          └──────────┬──────────┘   │
│          │                            │              │
│          └────────────┬───────────────┘              │
│                       ▼                              │
│             PostgreSQL  (asyncpg)                    │
└──────────────────────────────────────────────────────┘
```

---

## Modules

| Module | Description |
|--------|-------------|
| [`sessions/`](./sessions/README.md) | REST API for ingesting and retrieving recording sessions, interaction events, eye-tracking data, and screenshots |
| [`analysis/`](./analysis/README.md) | Friction detection algorithms, clickstream n-gram analysis, XES export for process mining, and gaze heatmap generation |
| `config.py` | Database connection, async session factory, optional API-key authentication |
| `main.py` | FastAPI application bootstrap, CORS middleware, router registration |
| `migrations/` | PostgreSQL DDL scripts |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Web framework | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| ORM | [SQLAlchemy 2 (async)](https://docs.sqlalchemy.org/) |
| Database | PostgreSQL via [asyncpg](https://github.com/MagicStack/asyncpg) |
| Validation | [Pydantic v2](https://docs.pydantic.dev/) |
| Heatmaps | NumPy · SciPy · Matplotlib · Pillow |

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+

### 1 · Clone & install

```bash
git clone <repo-url>
cd InteractionMonitoring
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2 · Configure the database

```bash
# Create the database
createdb monitoring

# Apply migrations
psql -d monitoring -f migrations/001_create_sessions_tables.sql
```

The server connects to `postgresql+asyncpg://postgres:postgres@localhost/monitoring` by default.  
Override with the `DATABASE_URL` environment variable.

### 3 · Run

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 4 · (Optional) API Key

Set `API_KEY` in your environment to enable Bearer-token authentication on all endpoints:

```bash
export API_KEY=mysecretkey
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost/monitoring` | PostgreSQL connection string |
| `API_KEY` | *(unset — auth disabled)* | Bearer token required on all endpoints when set |

---

## API Overview

Once running, visit `/docs` for the full interactive Swagger UI.  
A brief summary of the main endpoint groups:

| Prefix | Purpose |
|--------|---------|
| `GET /health` | Liveness check |
| `POST /sessions` | Upload a complete recording session |
| `GET /sessions` | List sessions with filtering & pagination |
| `GET /sessions/stats` | Aggregate statistics across all sessions |
| `GET /sessions/{id}` | Session detail + events |
| `POST /sessions/eye-tracking` | Upload an eye-tracking session |
| `POST /sessions/screenshot` | Upload a screenshot (base64 PNG) |
| `GET /analysis/friction/{id}` | Run friction analysis on a session |
| `GET /analysis/clickstream/{id}` | Run n-gram clickstream analysis |
| `GET /analysis/xes/{id}` | Export session as XES for process mining |
| `GET /analysis/heatmap/{id}` | Generate a gaze-point heatmap image |

---


## Related Repositories

> `[ PLACEHOLDER — links to the frontend / GLSP plugin repositories ]`

---

## License

> `[ PLACEHOLDER ]`
