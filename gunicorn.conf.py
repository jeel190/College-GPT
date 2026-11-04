import os

# Cap thread pools for numerical libraries to stay within 512MB RAM
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Gunicorn Production Configuration for Render Cloud
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
workers = 1
threads = 1  # Single thread: avoids thread-pool memory contention on 512MB container
timeout = 300  # 5 minutes: eliminates [CRITICAL] WORKER TIMEOUT
keepalive = 10
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50
preload_app = False
