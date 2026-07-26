# 🚨 Incident Copilot

**Incident response copilot featuring a multi-agent system (LangGraph), RAG, and mandatory human approval before any actual corrective action.**

A portfolio project built to practically apply observability, RAG, multi-agent systems, and human-in-the-loop — using Python, Docker, LangGraph, LangChain, and Postgres.

---

## Table of Contents

- [What is this project](https://www.google.com/search?q=%23what-is-this-project)
- [Why this matters in the industry](https://www.google.com/search?q=%23why-this-matters-in-the-industry)
- [Architecture](https://www.google.com/search?q=%23architecture)
- [Tech Stack](https://www.google.com/search?q=%23tech-stack)
- [How to run](https://www.google.com/search?q=%23how-to-run)
- [How to test each part](https://www.google.com/search?q=%23how-to-test-each-part)
- [Architectural decisions and learnings](https://www.google.com/search?q=%23architectural-decisions-and-learnings)
- [Automated testing and CI](https://www.google.com/search?q=%23automated-testing-and-ci)
- [Known limitations and next steps](https://www.google.com/search?q=%23known-limitations-and-next-steps)
- [Repository structure](https://www.google.com/search?q=%23repository-structure)
- [License](https://www.google.com/search?q=%23license)

---

## What is this project

When a software system (a website, an app, an API) becomes slow, stops responding, or consumes excessive resources, this is called an **incident**. In any company operating production software, there is a team (often called **SRE** — _Site Reliability Engineering_) responsible for identifying these issues quickly and resolving them before they impact many users.

The traditional process goes like this: an automated alert triggers, an engineer receives a notification, they must **investigate** (metrics, logs, internal documentation on "what to do when X happens"), and only then decide and apply a fix. This manual process is slow and heavily relies on the experience of the engineer on call.

This project builds an **AI Copilot** that automates the _investigation and diagnostic_ phase: a multi-agent system that automatically receives the alert, searches a knowledge base (runbooks), and proposes a diagnosis and corrective action in seconds instead of minutes or hours.

**The most crucial aspect of the project**: the system **never executes a corrective action on its own**. It only recommends actions, requiring a real human to review and approve before any actual changes occur (**human-in-the-loop**). This is essential because AI can make mistakes, and production actions (like restarting a server) can have severe consequences if applied indiscriminately.

<img src="./shows/Incident-Copilot-show1.GIF" alt="show 1 of the project (in 1.75x velocity" width="650" />
<img src="./shows/Incident-Copilot-show2.GIF" alt="show 2 of the project (in 1.75x velocity" width="650" />

## Why this matters in the industry

Production incidents are expensive—not only in lost revenue but also in technical team time (and stress). A widely used industry metric is **MTTR** (_Mean Time To Resolution_); reducing this time is a constant priority for tech companies. An entire market exists for this, known as **AIOps** (_AI for IT Operations_). Two real-world application examples:

- **E-commerce during Black Friday**: the checkout slows down. Instead of the on-call team frantically digging through dashboards, the copilot immediately surfaces "likely root cause: database connection pool exhaustion; recommended action: increase pool size," requiring only human confirmation.
- **SaaS with an API relied upon by external systems**: the API goes down at 3 AM. The on-call engineer (who just woke up with zero context) receives an initial diagnosis based on the company's runbooks instead of starting from scratch.

This project is a lean implementation of this concept, built to learn and demonstrate the underlying technical components: observability, RAG, multi-agent systems, and human approval.

## Architecture

```
app-fake (measures real CPU via cgroup + runs stress-ng on demand)
      │  scrape every 5s
      ▼
prometheus (evaluates rules) ──alert──▶ alertmanager (groups and sends)
                                              │  HTTP POST webhook
                                              ▼
                                    agent-orchestrator
                                    ┌─────────────────────────────┐
                                    │  LangGraph:                 │
                                    │  triage → retrieval →       │
                                    │  diagnosis → human          │
                                    │  approval → action execution│
                                    └─────────────────────────────┘
                                       │ query          │ state
                                       ▼                ▼
                                  rag-service        postgres-agent
                                       │
                                       ▼
                    runbooks/*.md → sentence-transformers → qdrant

                                       ▲
                                       │
                                  dashboard (Streamlit)
                         GET /processing, /pending, /incidents
                         POST /approve/{thread_id}

```

**End-to-end flow**: a monitored service (`app-fake`) exposes metrics → Prometheus detects an anomaly and triggers an alert → Alertmanager notifies `agent-orchestrator` → a 5-agent graph (LangGraph) performs triage, retrieves relevant runbooks (RAG), and generates a diagnosis using an LLM → the graph **pauses**, waiting for a human to approve or reject via the dashboard → only then (if approved) is the corrective action actually executed via the Docker SDK.

## Tech Stack

| Layer                 | Technology                                                            | Why                                                                                                                  |
| --------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Agent Orchestration   | **LangGraph**                                                         | Explicit multi-agent workflow control + native pause/resume support (`interrupt()`), essential for human-in-the-loop |
| LLM                   | **Google Gemini API** (`gemma-4-31b-it`) via `langchain-google-genai` | Cost-effective model, sufficient for structured tasks (higher budget yields better performance)                      |
| RAG / Semantic Search | **Qdrant** + `sentence-transformers` (`all-MiniLM-L6-v2`)             | Local embeddings (no API cost, no external dependency)                                                               |
| Backend               | **FastAPI** (Python)                                                  | Asynchronous, easy to expose endpoints for agents and human approval                                                 |
| Graph Persistence     | **PostgreSQL** (LangGraph checkpointer)                               | Paused incident state survives container restarts                                                                    |
| Observability         | **Prometheus** + **Alertmanager**                                     | Industry standard for metrics and alerting                                                                           |
| Interface             | **Streamlit**                                                         | Rapid functional dashboard without needing a dedicated frontend                                                      |
| Infrastructure        | **Docker Compose**                                                    | All services isolated and reproducible on any machine                                                                |
| Testing / CI          | **pytest** + **GitHub Actions**                                       | Automated testing of pure system components, running on every push                                                   |

## How to run

```bash
git clone git@github.com:Lucas-Darcio/Incident-Copilot.git
cd Incident-Copilot

cp .env.example .env
# edit .env and set GOOGLE_API_KEY and POSTGRES_PASSWORD

docker compose up --build

```

> The initial build takes a few minutes as `rag-service` downloads PyTorch (CPU-only) and the embedding model during image construction.

**Available Services:**

| Service              | URL                             | Description                             |
| -------------------- | ------------------------------- | --------------------------------------- |
| `app-fake`           | http://localhost:8000/docs      | Monitored service (simulates incidents) |
| `prometheus`         | http://localhost:9090           | Metrics and alerts                      |
| `alertmanager`       | http://localhost:9093           | Alert notifications                     |
| `agent-orchestrator` | http://localhost:8001/docs      | Agent graph + approval API              |
| `rag-service`        | http://localhost:8002/docs      | Semantic search across runbooks         |
| `qdrant`             | http://localhost:6333/dashboard | Vector database                         |
| `dashboard`          | http://localhost:8501           | **Human approval panel**                |

## How to test each part

**1. Trigger a real incident** (high CPU usage up to 120s, capped by container resource limits):

```bash
curl -X POST http://localhost:8000/chaos/start

```

Open **http://localhost:8501** — the incident appears almost immediately with "🧠 Analyzing...", and a few seconds later displays a full diagnosis along with approve/reject buttons.

**2. Test without waiting for Prometheus** (faster for development):

```bash
curl -X POST http://localhost:8001/diagnose \
  -H "Content-Type: application/json" \
  -d '{"alertname": "HighCPUUsage", "summary": "High CPU in app-fake:8000",
        "description": "97% usage", "severity": "critical", "instance": "app-fake:8000"}'

# copy the thread_id from the response and approve/reject:
curl -X POST http://localhost:8001/approve/YOUR_THREAD_ID \
  -H "Content-Type: application/json" -d '{"approved": true}'

```

**3. Test RAG in isolation:**

```bash
curl -X POST http://localhost:8002/ingest
curl -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{"query": "container consuming too much processing power", "top_k": 3}'

```

Notice that the search finds the correct runbook even if the word "CPU" isn't in the query—this is semantic search (meaning-based) rather than keyword matching.

## Architectural decisions and learnings

This section documents key technical decisions and their rationale, organized by topic rather than chronological order.

### Observability and container resource measurement

- **`cpu_usage_percent` is read directly from the container's cgroup** (the same mechanism used by `docker stats`), rather than pure `psutil.cpu_percent()`. Reason: inside a Linux container, `/proc/stat` reflects the host machine's total capacity, not what was allocated to that container. Pure `psutil` produces artificially low numbers that never cross alert thresholds.
- **Metrics are expressed as a percentage of the container's _own limit_** (e.g., 100% = using all allocated CPU), rather than a percentage of a single host core. This matches how production tools (cAdvisor, Kubernetes) calculate utilization—the core question is "is it using its full allocated capacity?", not "how many host cores is it using?".
- **`stress-ng` runs inside the monitored container itself** (via subprocess) rather than from an external "chaos injection" container. This ensures deterministic and reproducible behavior across machines. While an external container competing for physical cores represents a real scenario ("noisy neighbor"), its outcome depends on the host machine's core count, making tests inconsistent.

### RAG: chunking and embedding selection

- **Markdown section chunking** (`## Symptoms`, `## Recommended actions`, etc.) instead of fixed character counts. Runbooks already have predictable structures where each section is semantically cohesive, preventing ideas from being split mid-sentence—a common RAG pitfall.
- **Contextual Chunking**: Each chunk is prefixed with the document title + section name before embedding generation. Without this, a section like "Recommended actions: restart container" lacks context. The prefix preserves semantic context within the generated vector.
- **Local Embeddings** (`sentence-transformers`, `all-MiniLM-L6-v2` model) over paid APIs (OpenAI/Cohere). It is a lightweight model (~80MB), runs on CPU, incurs no recurring costs, and eliminates network dependencies for this step.

### Agent Orchestration: Why LangGraph (not just classic LangChain)

LangChain's legacy pattern (`AgentExecutor`, where an agent autonomously decided which tools to call in a loop) is now **built on top of LangGraph under the hood**, and official documentation recommends LangGraph for anything non-trivial. Key advantages for this project:

- **Multiple agents with fixed roles** (triage → retrieval → diagnosis) map naturally to graph nodes with explicit flow control.
- **Human-in-the-loop requires `interrupt()` + checkpointer** — classic `AgentExecutor` lacks a direct equivalent.
- Tools, messages (`SystemMessage`/`HumanMessage`), and chat models remain pure LangChain — LangGraph operates as an orchestration layer above them.

### LLM Cost and Call Resilience

- **Alert deduplication via `fingerprint**`: Alertmanager periodically re-sends a `firing`alert while active. Without deduplication, this would re-trigger the LLM on every re-send of the SAME incident. The`agent-orchestrator`ignores duplicate fingerprints, releasing state only when the alert is`resolved`.
- **Multi-tiered fallback JSON parsing**: Smaller/cheaper models (like Gemma used here) occasionally truncate or emit malformed JSON. The parser attempts, in order: (1) valid full JSON, (2) partial recovery via regex tolerant to truncated strings, (3) total fallback to raw text. In all cases, **uncertainty never turns into automation** — the `acao_automatizavel` field defaults to `false` whenever it cannot be confirmed.
- **Asynchronous webhook response**: Alertmanager's `group_interval` defines its response timeout. Because processing (RAG + LLM) can exceed this window, `/webhook` responds immediately (acknowledging receipt) and processes work in the background (`BackgroundTasks`), preventing false "notify failed" states in Alertmanager.

### True Human-in-the-loop

- **LangGraph's `interrupt()` pauses the execution graph** prior to any corrective action, exposing the diagnosis via `GET /pending`. Execution resumes only when `POST /approve/{thread_id}` invokes `Command(resume=...)`.
- **Postgres Checkpointer** (non-volatile memory): An incident might remain paused awaiting human review for minutes or hours; state must survive container restarts of `agent-orchestrator`.
- **Auto-resolution of pending incidents**: If the underlying alert resolves itself (e.g., `stress-ng` times out) before human intervention, the graph automatically resumes with `approved=False`. It makes no sense to "fix" a resolved issue, preventing incidents from remaining perpetually pending.
- **Security Note**: The `agent-orchestrator` connects directly to the host's Docker socket (`/var/run/docker.sock`) to execute real actions. In practice, this grants root-level host access to the container—acceptable for a local portfolio project, but in production, this should be isolated behind an intermediary API with a strict command allowlist.

### Asynchrony and User Experience

- **"Analyzing" status state**: Extracting alert summaries (`extrair_info_alerta`) is pure text interpretation without I/O blocking. It executes immediately upon receiving an alert, allowing the dashboard to display the incident instantly (with a "🧠 Analyzing..." indicator) rather than staying silent during background RAG + LLM processing.

### Testability: Separating Pure Logic from I/O

- **`parsing.py`** (agent-orchestrator) and **`chunking.py`** (rag-service) contain pure functions (no network calls, LLMs, or Docker dependencies). This allows testing bug-prone logic—such as parsing malformed responses or markdown chunking—with fast unit tests independent of external infrastructure.

## Automated testing and CI

```bash
# rag-service (fast, no PyTorch)
cd rag-service && pip install -r requirements-dev.txt && pytest tests/ -v

# agent-orchestrator (requires full dependencies)
cd agent-orchestrator
pip install -r requirements.txt -r requirements-dev.txt
GOOGLE_API_KEY=dummy pytest tests/ -v

```

A GitHub Actions workflow (`.github/workflows/tests.yml`) runs these tests automatically on every `push`/PR. Current coverage:

- `parsing.py`: alert extraction, LLM response normalization, valid/truncated/invalid JSON parsing.
- `chunking.py`: splitting runbooks by section, edge cases (empty documents, empty sections, missing titles).
- `execute_action_node`: successful restarts, missing containers, rejected actions, non-automatable actions, generic Docker failures — all using a **mocked** Docker client (no actual socket access required).

## Known limitations and next steps

Intentionally documented to highlight trade-offs:

- **No Authentication**: Anyone with network access can directly call `/approve`. Acceptable for a local project; production would require authentication (API keys, OAuth).
- **No Expiration for Pending Incidents**: Unapproved/unrejected incidents that do not auto-resolve linger indefinitely in Postgres. Implementing a TTL-based expiration background job is a logical next step.
- **Unpinned LangChain/LangGraph Versions**: Rapid ecosystem evolution makes pinning via `pip freeze` recommended prior to serious production use.
- **No Real "Noisy Neighbor" Simulation**: Chaos engineering executes inside the monitored container rather than as external resource contention (conscious decision, see architectural decisions above).

## Repository structure

```
Incident-Copilot/
├── app-fake/             # Monitored service (metrics + chaos engineering)
├── prometheus/           # Metrics and alert rule configurations
├── alertmanager/         # Alert notification routing configuration
├── rag-service/          # Semantic search engine (embeddings + Qdrant)
│   ├── chunking.py       #   Pure chunking logic (testable)
│   └── tests/
├── agent-orchestrator/   # Multi-agent graph (LangGraph) + API
│   ├── parsing.py        #   Pure parsing logic (testable)
│   ├── graph.py          #   Graph definition and 5 agents configuration
│   └── tests/
├── dashboard/            # Streamlit approval dashboard
├── runbooks/             # Knowledge base (markdown documents)
├── .github/workflows/    # CI (GitHub Actions)
├── docker-compose.yml
└── .env.example

```

## License

This project is licensed under the MIT License — see [LICENSE](https://www.google.com/search?q=LICENSE).
