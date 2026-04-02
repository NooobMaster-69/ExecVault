<p align="center">
  <h1 align="center">⚡ Distributed Code Execution Platform</h1>
  <p align="center">
    A scalable, production-ready platform for executing untrusted code in isolated environments — powered by FastAPI, Docker sandboxing, and an async job queue.
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-sandbox-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-optional-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" />
</p>

---

## 🎯 What is this?

This platform lets you **submit code via a REST API** and have it executed **safely inside Docker containers** (or sandboxed subprocesses as a fallback). It handles the full lifecycle — queuing, execution, timeout enforcement, and result retrieval — all through a clean, async API.

**Perfect for:** online judges, coding playgrounds, educational platforms, CI pipelines, or any app that needs to run user-submitted code securely.

### ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🐳 **Docker Sandboxing** | Code runs in isolated containers with CPU, memory, PID limits and no network access |
| 🔄 **Subprocess Fallback** | Automatically falls back to sandboxed local execution if Docker isn't available |
| 📡 **REST API** | Clean FastAPI endpoints with OpenAPI/Swagger docs |
| 📬 **Async Job Queue** | Submit code and poll for results — no blocking |
| 🧵 **Worker Thread Pool** | Configurable number of concurrent execution workers |
| 🔴 **Redis Support** | Optional Redis backend for distributed multi-process/multi-machine scaling |
| 🌐 **Multi-Language** | Python, Node.js, Bash (Docker) + PowerShell (subprocess) |
| 🛡️ **Security Layer** | Regex-based dangerous pattern detection blocks `eval`, `exec`, `subprocess`, `socket`, `rm -rf`, etc. |
| ⏱️ **Timeout Handling** | Per-job configurable timeouts with graceful termination |
| 📊 **Stats & Health** | Built-in `/health` and `/stats` endpoints for monitoring |

---

## 🏗️ Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Client / cURL               │
                    └──────────────────┬──────────────────────┘
                                       │ HTTP
                                       ▼
                    ┌─────────────────────────────────────────┐
                    │          FastAPI REST Server              │
                    │                                           │
                    │  POST /execute    →  Queue Job            │
                    │  GET  /status/:id →  Check Status         │
                    │  GET  /result/:id →  Get Output           │
                    │  GET  /health     →  Health Check         │
                    │  GET  /stats      →  Queue Statistics     │
                    └──────────────────┬──────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                   ┌─────────────┐          ┌─────────────┐
                   │  In-Memory  │    OR    │    Redis     │
                   │   Queue +   │          │   Queue +    │
                   │   Store     │          │   Store      │
                   └──────┬──────┘          └──────┬──────┘
                          │                        │
                          ▼                        ▼
                    ┌─────────────────────────────────────────┐
                    │           Worker Thread Pool              │
                    │         (configurable threads)            │
                    └──────────────────┬──────────────────────┘
                                       │
                          ┌────────────┴────────────┐
                          ▼                         ▼
                   ┌─────────────┐          ┌─────────────┐
                   │   Docker    │          │ Subprocess   │
                   │  Container  │          │  (fallback)  │
                   │ --memory    │          │  sandboxed   │
                   │ --cpus      │          │  env vars    │
                   │ --network=  │          │              │
                   │   none      │          │              │
                   └─────────────┘          └─────────────┘
```

---

## 📁 Project Structure

```
distributed-code-executor/
│
├── api/
│   ├── __init__.py
│   └── main.py                 # FastAPI app with all REST endpoints
│
├── worker/
│   ├── __init__.py
│   └── worker.py               # Thread pool worker + standalone entrypoint
│
├── executor/
│   ├── __init__.py
│   └── docker_executor.py      # Docker & subprocess execution engine
│
├── job_queue/
│   ├── __init__.py
│   └── queue_manager.py        # In-memory & Redis queue/store backends
│
├── models/
│   ├── __init__.py
│   └── job.py                  # Job dataclass & JobStatus enum
│
├── utils/
│   ├── __init__.py             # Socket/auth helpers (legacy TCP mode)
│   └── config.py               # Environment-based configuration
│
├── server.py                   # Legacy TCP socket server
├── client.py                   # Legacy TCP socket client
├── executor.py                 # Legacy subprocess executor
├── utils.py                    # Legacy socket utilities
│
├── test_api_e2e.py             # End-to-end API test suite
├── test_api_more_e2e.py        # Extended API tests
├── test_e2e.py                 # Legacy TCP server tests
│
├── requirements.txt
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+**
- **Docker** *(optional but recommended for sandboxed execution)*
- **Redis** *(optional — only needed for distributed/multi-process mode)*

### Installation

```bash
# Clone the repository
git clone https://github.com/NooobMaster-69/distributed-code-executor.git
cd distributed-code-executor

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 💻 Usage

### Mode 1: Single Process (Quick Start)

The simplest way to run — API and workers in one process, jobs stored in memory:

```bash
python -m api.main
```

Or with uvicorn directly:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

> 📖 **Swagger UI** available at: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Mode 2: Distributed (Redis + Separate Workers)

Scale horizontally by running the API and workers as separate processes backed by Redis.

**Terminal 1 — API server (no embedded worker):**

```bash
# Linux/macOS
export REDIS_URL=redis://localhost:6379/0
export RUN_EMBEDDED_WORKER=false
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Windows
set REDIS_URL=redis://localhost:6379/0
set RUN_EMBEDDED_WORKER=false
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2+ — Worker processes:**

```bash
# Linux/macOS
export REDIS_URL=redis://localhost:6379/0
python -m worker.worker

# Windows
set REDIS_URL=redis://localhost:6379/0
python -m worker.worker
```

> 💡 **Tip:** Spin up multiple worker processes across different machines pointing to the same `REDIS_URL` to scale execution capacity.

---

## 📡 API Reference

### `POST /execute` — Submit Code

```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{
    "code": "print(\"Hello, World!\")",
    "language": "python",
    "timeout": 10
  }'
```

**Response `202 Accepted`:**

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "QUEUED",
  "message": "Job queued for execution."
}
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | *(required)* | Source code to execute (max 50KB) |
| `language` | string | `"python"` | `python`, `node`, `bash`, or `powershell`* |
| `timeout` | integer | `10` | Execution timeout in seconds (1–30) |

*\* `powershell` is only available in subprocess mode*

---

### `GET /status/{job_id}` — Check Job Status

```bash
curl http://localhost:8000/status/a1b2c3d4e5f6
```

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "SUCCESS"
}
```

---

### `GET /result/{job_id}` — Get Full Result

```bash
curl http://localhost:8000/result/a1b2c3d4e5f6
```

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "SUCCESS",
  "output": "Hello, World!\n",
  "stdout": "Hello, World!\n",
  "stderr": "",
  "error": "",
  "exit_code": 0,
  "timed_out": false,
  "language": "python",
  "execution_time": 0.0123,
  "execution_time_ms": 12.3,
  "created_at": "2026-04-02T18:30:00+00:00",
  "started_at": "2026-04-02T18:30:00.050+00:00",
  "completed_at": "2026-04-02T18:30:00.062+00:00"
}
```

---

### `GET /health` — Health Check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "worker_running": true,
  "embedded_worker": true,
  "executor_mode": "docker",
  "queue_backend": "memory"
}
```

---

### `GET /stats` — Queue Statistics

```bash
curl http://localhost:8000/stats
```

```json
{
  "queue_size": 0,
  "job_counts": {
    "SUCCESS": 42,
    "FAILED": 3,
    "TIMEOUT": 1
  }
}
```

---

## 🔄 Job Lifecycle

```
  ┌────────┐      ┌─────────┐      ┌─────────┐
  │ QUEUED │ ───▶ │ RUNNING │ ───▶ │ SUCCESS │
  └────────┘      └────┬────┘      └─────────┘
                       │
                       ├──────────▶ ┌────────┐
                       │            │ FAILED │
                       │            └────────┘
                       │
                       └──────────▶ ┌─────────┐
                                    │ TIMEOUT │
                                    └─────────┘
```

---

## 🔒 Security

The platform implements multiple layers of security:

1. **Docker Isolation** — Each execution runs in a disposable container with:
   - `--network=none` — No network access
   - `--read-only` — Read-only filesystem
   - `--memory=50m` — Memory cap
   - `--cpus=0.5` — CPU throttling
   - `--pids-limit=64` — Process limit

2. **Code Scanning** — Regex-based static analysis blocks dangerous patterns before execution:
   - System calls (`os.system`, `subprocess`, `ctypes`)
   - File operations (`shutil.rmtree`, `os.remove`)
   - Network access (`socket`, `requests`, `urllib`)
   - Code injection (`eval`, `exec`, `compile`)
   - Destructive commands (`rm -rf`, `format C:`)

3. **Sandboxed Environment** — Subprocess fallback strips all environment variables except `PATH`, `TEMP`, `HOME`, etc.

4. **Timeouts** — Per-job enforced timeouts with graceful termination.

---

## ⚙️ Configuration

All settings are controlled via **environment variables** — no config files needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | API bind address |
| `API_PORT` | `8000` | API port |
| `WORKER_THREADS` | `4` | Number of worker threads |
| `RUN_EMBEDDED_WORKER` | `true` | Start workers inside the API process |
| `REDIS_URL` | *(empty)* | Redis connection URL for distributed mode |
| `REDIS_KEY_PREFIX` | `exec:` | Key prefix for Redis entries |
| `DOCKER_MEMORY_LIMIT` | `50m` | Container memory limit |
| `DOCKER_CPU_LIMIT` | `0.5` | Container CPU limit |
| `DOCKER_PIDS_LIMIT` | `64` | Container process limit |
| `DOCKER_STOP_TIMEOUT_SEC` | `1` | Container stop timeout |

---

## 🧪 Testing

Run the end-to-end test suite against a running server:

```bash
# Start the server first
python -m api.main

# In another terminal, run tests
python test_api_e2e.py          # Core API tests
python test_api_more_e2e.py     # Extended tests (multi-language, edge cases)
```

---

## 🗂️ Legacy TCP Mode

The project also includes the original TCP socket-based server/client (before the REST API was built):

```bash
# Terminal 1
python server.py

# Terminal 2
python client.py
```

> These are preserved for reference and backward compatibility. The REST API is the recommended interface.

---

## 🛣️ Roadmap

- [ ] WebSocket support for real-time output streaming
- [ ] Rate limiting and API key authentication
- [ ] Persistent job history with database storage
- [ ] Web-based code editor UI
- [ ] Support for more languages (Go, Rust, Java, C++)
- [ ] Container image caching and pre-warming

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/NooobMaster-69">NooobMaster-69</a>
</p>
