# Distributed Code Execution Platform

A backend platform for executing untrusted code in isolated environments. Submit code via REST API, have it run inside Docker containers (or sandboxed subprocesses), and poll for results.

Built with FastAPI, with optional Redis-backed job queues for horizontal scaling.

---

## Why

Running user-submitted code is a common need — online judges, coding playgrounds, educational tools, CI pipelines. The tricky part is doing it safely and at scale. This project handles sandboxing, queuing, timeouts, and result tracking so you don't have to roll your own.

---

## How it works

```
Client (cURL, frontend, etc.)
    |
    |  POST /execute
    v
FastAPI Server
    |
    |  enqueue
    v
Job Queue (in-memory or Redis)
    |
    |  dequeue
    v
Worker Thread Pool
    |
    |  execute
    v
Docker Container          ... or subprocess fallback
  --network=none               (sandboxed env)
  --read-only
  --memory=50m
  --cpus=0.5
```

1. Client submits code + language + timeout via `POST /execute`
2. Server creates a job, queues it, returns a `job_id`
3. A worker picks up the job and runs it in Docker (preferred) or subprocess (fallback)
4. Client polls `GET /result/{job_id}` to retrieve output

---

## Quick start

```bash
git clone https://github.com/NooobMaster-69/distributed-code-executor.git
cd distributed-code-executor

python -m venv venv
venv\Scripts\activate           # Windows
# source venv/bin/activate      # Linux/macOS

pip install -r requirements.txt
```

Start the server (API + workers in one process, in-memory queue):

```bash
python -m api.main
```

Swagger docs at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Distributed mode

If you need to scale workers across processes or machines, use Redis as the shared backend.

**API server:**

```bash
set REDIS_URL=redis://localhost:6379/0
set RUN_EMBEDDED_WORKER=false
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Worker (run as many as you want):**

```bash
set REDIS_URL=redis://localhost:6379/0
python -m worker.worker
```

All workers pointing to the same `REDIS_URL` will share the queue.

---

## API

### `POST /execute`

Submit code for execution.

```bash
curl -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"code": "print(\"hello\")", "language": "python", "timeout": 10}'
```

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "QUEUED",
  "message": "Job queued for execution."
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `code` | string | required | Max 50KB |
| `language` | string | `"python"` | `python`, `node`, `bash`, `powershell`* |
| `timeout` | int | `10` | 1-30 seconds |

\* `powershell` only available in subprocess mode.

### `GET /status/{job_id}`

Returns current status: `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`, or `TIMEOUT`.

### `GET /result/{job_id}`

Returns the full result including `stdout`, `stderr`, `exit_code`, `execution_time_ms`, timestamps, etc.

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "SUCCESS",
  "output": "hello\n",
  "stdout": "hello\n",
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

### `GET /health`

Server health, executor mode (docker/subprocess), queue backend (memory/redis).

### `GET /stats`

Queue depth and job counts by status.

---

## Job lifecycle

```
QUEUED  -->  RUNNING  -->  SUCCESS
                      -->  FAILED
                      -->  TIMEOUT
```

---

## Security

**Docker isolation** (when Docker is available):
- `--network=none` — no outbound network
- `--read-only` — immutable filesystem
- `--memory=50m` — memory cap
- `--cpus=0.5` — CPU throttle
- `--pids-limit=64` — fork bomb protection
- Container is removed after execution (`--rm`)

**Code scanning** — before execution, submitted code is checked against patterns for:
- System calls (`os.system`, `subprocess`, `ctypes`)
- File destruction (`shutil.rmtree`, `os.remove`, `rm -rf`)
- Network access (`socket`, `requests`, `urllib`)
- Code injection (`eval`, `exec`, `compile`)

**Subprocess fallback** — when Docker isn't available, code runs with a stripped-down environment (only `PATH`, `TEMP`, `HOME`, etc. are kept).

**Timeouts** — enforced per-job, with graceful termination.

---

## Configuration

Everything is controlled through environment variables.

| Variable | Default | What it does |
|----------|---------|--------------|
| `API_HOST` | `0.0.0.0` | Bind address |
| `API_PORT` | `8000` | Port |
| `WORKER_THREADS` | `4` | Concurrent execution threads |
| `RUN_EMBEDDED_WORKER` | `true` | Run workers inside the API process |
| `REDIS_URL` | *(empty)* | Set to enable distributed mode |
| `REDIS_KEY_PREFIX` | `exec:` | Namespace for Redis keys |
| `DOCKER_MEMORY_LIMIT` | `50m` | Container memory limit |
| `DOCKER_CPU_LIMIT` | `0.5` | Container CPU limit |
| `DOCKER_PIDS_LIMIT` | `64` | Container PID limit |
| `DOCKER_STOP_TIMEOUT_SEC` | `1` | Seconds before force-killing container |

---

## Project structure

```
api/main.py                  FastAPI app, all endpoints
worker/worker.py             Thread pool, standalone entrypoint
executor/docker_executor.py  Docker + subprocess execution
job_queue/queue_manager.py   In-memory and Redis queue/store
models/job.py                Job dataclass, JobStatus enum
utils/config.py              Env-based settings

server.py, client.py         Legacy TCP socket interface
executor.py, utils.py        Legacy helpers (kept for reference)
```



---

