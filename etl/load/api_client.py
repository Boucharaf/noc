import logging

import requests

logger = logging.getLogger(__name__)


class NocApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 5):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def is_healthy(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/", timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def ingest_incident(self, payload: dict) -> dict | None:
        try:
            r = requests.post(
                f"{self.base_url}/api/incidents/ingest",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            logger.warning("Ingest failed for %s: %s", payload.get("node_code"), exc)
            return None

    def ingest_incidents_bulk(self, payloads: list[dict]) -> dict | None:
        """Post a whole collection pass in one request.

        The per-incident endpoint costs one unit of the ingest rate limit each,
        so a real active-alarm set (NetXMS reports ~1500) never fits through it.
        Timeout scales with the batch: this is one request the backend spends
        real time on, unlike the single-incident call.
        """
        try:
            r = requests.post(
                f"{self.base_url}/api/incidents/ingest/bulk",
                json={"incidents": payloads},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=max(self.timeout, 120),
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            logger.warning("Bulk ingest of %d incident(s) failed: %s", len(payloads), exc)
            return None

    def download_monthly_report(self, month: int, year: int, format: str = "pdf") -> bytes | None:
        try:
            r = requests.get(
                f"{self.base_url}/api/report/monthly",
                params={"month": month, "year": year, "format": format},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=max(self.timeout, 30),
            )
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            logger.warning("Report download failed for %s-%s: %s", year, month, exc)
            return None
