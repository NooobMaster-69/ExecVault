# Distributed Code Execution Platform

FastAPI REST API, pluggable job queue (in-memory or **Redis**), background workers, Docker-sandboxed execution with subprocess fallback, and the original TCP **server.py** / **client.py** stack.

**Note:** The queue package is named `job_queue/` (not `queue/`) because a top-level Python package called `queue` shadows the standard library `queue` module and breaks libraries such as `urllib3` / `requests`.

## Layout

```
project/
├── api/
│   └── main.py              # FastAPI app
├── worker/
│   └── worker.py            # Worker pool + `python -m worker.worker` entrypoint
├── executor/
│   └── docker_executor.py   # Docker + subprocess executor
├── job_queue/
│   └── queue_manager.py     # JobQueue, JobStore, Redis backends, build_queue_backend()
├── models/
│   └── job.py               # Job, JobStatus
├── utils/
│   ├── __init__.py          # Socket/auth helpers (legacy)
│   └── config.py            # Env-based settings
├── server.py                # Legacy TCP server
├── client.py                # Legacy TCP client
├── executor.py              # Legacy subprocess executor
├── utils.py                 # Legacy flat utils (socket)
├── requirements.txt
└── README.md
```

## Install

```bash
pip install -r requirements.txt
```

## 1. API + embedded worker (default, in-memory queue)

Single process: API accepts jobs, workers run in background threads, jobs stored in memory.

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Or:

```bash
python -m api.main
```

Swagger: `http://localhost:8000/docs`

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Bind address |
| `API_PORT` | `8000` | Port |
| `WORKER_THREADS` | `4` | Worker threads |
| `RUN_EMBEDDED_WORKER` | `true` | Start workers inside API process |
| `REDIS_URL` | *(empty)* | If set, use Redis queue + store |
| `REDIS_KEY_PREFIX` | `exec:` | Redis key prefix |
| `DOCKER_MEMORY_LIMIT` | `50m` | `docker run --memory` |
| `DOCKER_CPU_LIMIT` | `0.5` | `docker run --cpus` |
| `DOCKER_PIDS_LIMIT` | `64` | `docker run --pids-limit` |
| `DOCKER_STOP_TIMEOUT_SEC` | `1` | `docker run --stop-timeout` |
| `AUTH_SECRET` | *(dev default)* | HMAC secret for `server.py` / `client.py` |

## 2. Distributed mode (Redis + separate worker processes)

**Terminal A — API only (no embedded worker):**

```bash
set REDIS_URL=redis://localhost:6379/0
set RUN_EMBEDDED_WORKER=false
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Terminal B — Worker(s):**

```bash
set REDIS_URL=redis://localhost:6379/0
python -m worker.worker
```

Run multiple workers or machines against the same `REDIS_URL` to scale execution.

## 3. Test the API

With the server running:

```bash
curl -X POST http://localhost:8000/execute ^
  -H "Content-Type: application/json" ^
  -d "{\"code\": \"print('Hello')\", \"language\": \"python\", \"timeout\": 10}"
```

**Response (202):**

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "QUEUED",
  "message": "Job queued for execution."
}
```

```bash
curl http://localhost:8000/status/<job_id>
curl http://localhost:8000/result/<job_id>
curl http://localhost:8000/health
curl http://localhost:8000/stats
```

**Example result JSON:**

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "SUCCESS",
  "output": "Hello\n",
  "stdout": "Hello\n",
  "stderr": "",
  "error": "",
  "exit_code": 0,
  "timed_out": false,
  "language": "python",
  "execution_time": 0.0123,
  "execution_time_ms": 12.3,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "..."
}
```

Automated suite (requires server on port 8000):

```bash
python test_api_e2e.py
```

## Job lifecycle

`QUEUED` → `RUNNING` → `SUCCESS` | `FAILED` | `TIMEOUT`

## Legacy socket server

```bash
python server.py
python client.py
```

## License

MIT
