"""
Gunicorn settings for Diction Masters.

    gunicorn -c gunicorn.conf.py config.wsgi:application

Most things can be overridden with an environment variable, so the same
file works on a small VPS and a bigger server.
"""

import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")

# Two per core plus one is the usual starting point for a site that
# spends much of its time waiting on the database and on R2.
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "gthread")

# Long enough for a big video upload to reach R2 before a worker is
# considered stuck.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 180))
graceful_timeout = 30
keepalive = 5

# Restart workers now and then so a slow leak can never build up.
max_requests = 1000
max_requests_jitter = 100

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
forwarded_allow_ips = "*"      # behind nginx on the same machine
