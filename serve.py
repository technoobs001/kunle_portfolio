#!/usr/bin/env python3
"""
Tiny local web server with production-style caching headers.

    python serve.py            ->  http://localhost:8000/archive.html
    python serve.py 9000       ->  another port

Why use it: the gallery reads gallery/manifest.json with fetch(), which browsers
block when a page is opened straight from disk. This server also shows exactly
how the headers should look on your real host (see _headers / .htaccess /
nginx.example.conf for copy-paste versions).

Caching policy
  gallery/generated/*   file names contain a content hash, so they never change:
                        Cache-Control: public, max-age=31536000, immutable
  gallery/manifest.*    must always be revalidated so new photos appear at once:
                        Cache-Control: no-cache   (browser still gets cheap 304s)
  assets/*, fonts/*     rarely change:  public, max-age=604800, stale-while-revalidate=86400
  *.html, *.css, *.js   revalidate on every visit (cheap 304 when unchanged)
"""
import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        p = self.path.split("?", 1)[0]
        if p.startswith("/gallery/generated/"):
            cc = "public, max-age=31536000, immutable"
        elif p.startswith("/gallery/manifest"):
            cc = "no-cache"
        elif p.startswith(("/assets/", "/fonts/", "/gallery/frames/", "/gallery/stickers/")):
            cc = "public, max-age=604800, stale-while-revalidate=86400"
        else:
            cc = "no-cache"
        self.send_header("Cache-Control", cc)
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webp": "image/webp", ".avif": "image/avif", ".woff2": "font/woff2",
                      ".js": "text/javascript", ".json": "application/json"}


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), Handler) as httpd:
        print(f"Serving {ROOT} at http://localhost:{port}/archive.html  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nbye")
