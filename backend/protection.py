import hashlib
import hmac
import ipaddress
import time
from datetime import datetime

from backend.compat import ZoneInfo
from backend.validation import InboxError


class Protection:
    """Durable counters; no raw client addresses or session tokens in storage."""

    def __init__(self, config, database):
        self.config = config
        self.database = database

    def initialize(self):
        with self.database.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS limits ("
                "key TEXT NOT NULL, period TEXT NOT NULL, used INTEGER NOT NULL, "
                "PRIMARY KEY(key, period))"
            )

    def day(self):
        return datetime.now(ZoneInfo(self.config.timezone)).date().isoformat()

    def charge(self, counters):
        # All counters are checked and incremented in one transaction.
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for key, period, amount, maximum in counters:
                row = connection.execute(
                    "SELECT used FROM limits WHERE key = ? AND period = ?", (key, period)
                ).fetchone()
                if (row["used"] if row else 0) + amount > maximum:
                    raise InboxError(429, "Gönderim sınırına ulaşıldı. Biraz sonra tekrar deneyin.")
                connection.execute(
                    "INSERT INTO limits VALUES (?, ?, ?) ON CONFLICT(key, period) "
                    "DO UPDATE SET used = used + excluded.used",
                    (key, period, amount),
                )
            # Minutes live for two buckets; only today's daily counter is needed.
            connection.execute(
                "DELETE FROM limits WHERE (period LIKE 'm:%' AND period < ?) "
                "OR (period LIKE 'd:%' AND period < ?)",
                (f"m:{int(time.time()) // 60 - 1:012d}", "d:" + self.day()),
            )

    def check_request(self, request):
        secret = self.config.gateway_secret
        if secret:
            supplied = request.headers.get("x-inbox-gateway", "")
            if not hmac.compare_digest(supplied.encode(), secret.get_secret_value().encode()):
                raise InboxError(403, "Bu bağlantı üzerinden işlem yapılamıyor.")
            address = request.headers.get("x-inbox-client-ip", "")
        else:
            address = request.client.host if request.client else "local"
        try:
            ip = ipaddress.ip_address(address)
            # Group IPv6 privacy addresses in one /64, preventing trivial rotation.
            address = (
                str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)
            )
        except ValueError:
            if secret:
                raise InboxError(403, "Geçersiz bağlantı.") from None
            address = "local"
        salt = secret.get_secret_value() if secret else "local-only"
        client = hmac.new(salt.encode(), address.encode(), hashlib.sha256).hexdigest()
        minute = f"m:{int(time.time()) // 60:012d}"
        counters = [
            ("request:" + client, minute, 1, self.config.requests_per_minute),
            ("requests:global", minute, 1, 600),
        ]
        if request.url.path == "/api/v1/sessions" and request.method == "POST":
            counters.extend(
                [
                    ("session:" + client, minute, 1, self.config.sessions_per_minute),
                    ("sessions:global", "d:" + self.day(), 1, self.config.sessions_per_day),
                ]
            )
        self.charge(counters)
        if request.url.path.endswith("/files"):
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT used FROM limits WHERE key = 'upload' AND period = ?",
                    ("d:" + self.day(),),
                ).fetchone()
            if row and row["used"] >= self.config.daily_upload_mb * 1024 * 1024:
                raise InboxError(429, "Günlük gönderim sınırına ulaşıldı.")

    def upload_bytes(self, size):
        if not size:
            return
        maximum = self.config.daily_upload_mb * 1024 * 1024
        period = "d:" + self.day()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT used FROM limits WHERE key = 'upload' AND period = ?", (period,)
            ).fetchone()
            total = (row["used"] if row else 0) + size
            # Commit a saturated counter even when the crossing chunk is rejected.
            # Otherwise repeated too-large chunks could leave the budget unspent.
            connection.execute(
                "INSERT INTO limits VALUES ('upload', ?, ?) "
                "ON CONFLICT(key, period) DO UPDATE SET used = excluded.used",
                (period, min(total, maximum)),
            )
        if total > maximum:
            raise InboxError(429, "Günlük gönderim sınırına ulaşıldı.")
