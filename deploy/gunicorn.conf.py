"""Sample gunicorn configuration for MCP Agent Mail."""

import multiprocessing
from pathlib import Path

# Bind to same interface/port as default settings; override via GUNICORN_CMD_ARGS if needed.
bind = "0.0.0.0:8765"

# Use number of workers proportional to cores; uvicorn workers handle async FastAPI app.
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"

# Graceful timeouts to match long running tasks.
keepalive = 5
graceful_timeout = 180  # Increased to 180 seconds (60% of timeout) to better match long-running operations
timeout = 300  # Increased from 120 to 300 seconds (5 minutes) to handle slow fetch operations

# Location for PID/log files (customize as desired).
pidfile = str(Path("/var/run/mcp-agent-mail/gunicorn.pid"))
errorlog = "-"  # stderr
accesslog = "-"  # stdout
loglevel = "info"

# Optional: forward standard proxy headers.
forwarded_allow_ips = "*"
