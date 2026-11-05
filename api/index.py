import os
import sys
import urllib.parse

# Ensure root directory is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app

class VercelPathFixMiddleware:
    """
    Vercel rewrites routes into /api/index?path=:match*.
    This WSGI middleware extracts the original intended path and restores PATH_INFO.
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = environ.get("QUERY_STRING", "")
        params = urllib.parse.parse_qs(qs)

        path_val = params.get("path", [""])[0].strip()
        if path_val:
            resolved_path = "/" + path_val.lstrip("/")
        else:
            orig = (
                environ.get("HTTP_X_FORWARDED_URI") or
                environ.get("HTTP_X_MATCHED_PATH") or
                environ.get("RAW_URI") or
                environ.get("REQUEST_URI") or
                environ.get("PATH_INFO") or
                "/"
            ).split("?")[0]
            if orig.startswith("/api/index"):
                rest = orig[len("/api/index"):]
                resolved_path = rest if rest else "/"
            else:
                resolved_path = orig

        if not resolved_path:
            resolved_path = "/"

        environ["PATH_INFO"] = resolved_path
        environ["SCRIPT_NAME"] = ""
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathFixMiddleware(app.wsgi_app)
