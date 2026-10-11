"""Isolated tunnel probe: no uploads, filesystem serving or project imports."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ProbeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):
        if self.path not in ("/", "/healthz"):
            self.send_error(404)
            return
        body = (
            b'{"status":"ok","service":"qr-print-inbox-tunnel-test"}'
            if self.path == "/healthz"
            else (
                '<!doctype html><html lang="tr"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>QR File Inbox Test</title><h1>Tünel bağlantısı çalışıyor</h1>'
                '<p>Bu sayfa yalnızca bağlantı testidir. Dosya yüklenmez.</p></html>'
            ).encode()
        )
        self.send_response(200)
        content_type = (
            "application/json" if self.path == "/healthz" else "text/html; charset=utf-8"
        )
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print("Test sayfasi: http://127.0.0.1:8765 — durdurmak icin Ctrl+C", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", 8765), ProbeHandler).serve_forever()
    except KeyboardInterrupt:
        pass
