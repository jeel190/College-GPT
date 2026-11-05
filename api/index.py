import os
import sys

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app

class VercelPathFixMiddleware:
    """
    Vercel rewrites routes into /api/index, which overwrites PATH_INFO.
    This WSGI middleware restores the original requested path from Vercel's proxy headers.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        orig_path = (
            environ.get("HTTP_X_FORWARDED_URI") or
            environ.get("HTTP_X_MATCHED_PATH") or
            environ.get("RAW_URI") or
            environ.get("REQUEST_URI") or
            ""
        ).split("?")[0]

        if orig_path:
            environ["PATH_INFO"] = orig_path
        elif environ.get("PATH_INFO", "").startswith("/api/index"):
            rest = environ["PATH_INFO"][len("/api/index"):]
            environ["PATH_INFO"] = rest if rest else "/"

        if not environ.get("PATH_INFO"):
            environ["PATH_INFO"] = "/"

        environ["SCRIPT_NAME"] = ""
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathFixMiddleware(app.wsgi_app)
