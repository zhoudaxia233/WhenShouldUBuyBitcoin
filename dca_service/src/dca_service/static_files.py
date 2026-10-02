"""Static files that browsers never use stale.

Pages reference CSS and JS through asset_url(), whose ?v= changes with the
file contents, so a new page never pairs with an old cached file. Every
static response also carries Cache-Control: no-cache, so browsers revalidate
with the ETag (a cheap 304) instead of guessing how long a copy stays fresh.
"""
import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"


@lru_cache(maxsize=None)
def asset_url(name: str) -> str:
    digest = hashlib.md5((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
    return f"/static/{name}?v={digest}"


class RevalidatedStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
