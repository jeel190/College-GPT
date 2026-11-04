import os

# Gunicorn Production Configuration for Render Cloud
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
workers = 1
threads = 4
timeout = 300  # 5 minutes: prevents [CRITICAL] WORKER TIMEOUT on cloud inference
keepalive = 10
graceful_timeout = 30
