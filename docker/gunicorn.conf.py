# Gunicorn configuration for Horilla-HR
# This file provides advanced configuration options for the WSGI server
import multiprocessing
import os

# Bind settings
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
host = "0.0.0.0"
port = int(os.environ.get("PORT", "8000"))

# Worker settings
#
# multiprocessing.cpu_count() reflects the host's CPU count, not the memory
# limit of the container — on small/free-tier instances (e.g. Render's 512MB
# plan) that can still report several cores, producing far more workers than
# the available memory can hold. Each worker loads a full copy of the Django
# app (including heavy deps like spacy's en_core_web_sm), so too many workers
# reliably gets the process OOM-killed on constrained instances.
#
# Default to a conservative 2 workers; override explicitly per-environment
# with GUNICORN_WORKERS (e.g. set to 1 on Render's free 512MB plan, or higher
# on a bigger instance) rather than relying on CPU-count autodetection.
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 2))
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# preload_app is disabled with gthread workers to avoid ORM connection issues
preload_app = False

# Timeout settings
timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "horilla-hrms"

# Server mechanics
pidfile = "/tmp/gunicorn.pid"
user = None  # Run as current user in container
group = None
tmp_upload_dir = None

# Development settings
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"

# SSL settings (if needed)
# ssl_keyfile = os.environ.get('SSL_KEYFILE')
# ssl_certfile = os.environ.get('SSL_CERTFILE')
