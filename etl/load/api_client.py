import logging

import requests

logger = logging.getLogger(__name__)

# Keys the backend's bulk ingest endpoint is expected to return. Anything
# else — including a 200 OK whose body doesn't match this shape — is treated
# as a failure by ingest_incidents_bulk(), so a backend contract change
# surfaces as one clear "ingest failed" log line instead of a KeyError three
# call frames away, in code that has no idea an HTTP client was even involved.
_BULK_RESULT_KEYS = {"created", "resolved", "unknown_node"}


class NocApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

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
                headers=self._headers(),
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

        Returns None on any failure — network, HTTP status, or a 200 response
        that doesn't carry the three keys the caller relies on. That makes
        `if result is None` in tasks.collect_supervision the only branch that
        has to handle "the backend didn't give us usable numbers", instead of
        a malformed body raising a KeyError that skips every tool the loop
        hasn't reached yet (see the pipelines/tasks.py fix alongside this one).
        """
        if not payloads:
            # Nothing to report this pass for this tool — skip the round trip
            # (and whatever an empty `incidents` array does server-side)
            # rather than treating "no open incidents" as work to do.
            return {"created": 0, "resolved": 0, "unknown_node": 0}
        try:
            r = requests.post(
                f"{self.base_url}/api/incidents/ingest/bulk",
                json={"incidents": payloads},
                headers=self._headers(),
                timeout=max(self.timeout, 120),
            )
            r.raise_for_status()
            result = r.json()
        except requests.RequestException as exc:
            logger.warning(
                "Bulk ingest of %d incident(s) failed: %s", len(payloads), exc
            )
            return None

        if not isinstance(result, dict) or not _BULK_RESULT_KEYS.issubset(result):
            missing = _BULK_RESULT_KEYS - set(result if isinstance(result, dict) else {})
            logger.error(
                "Bulk ingest of %d incident(s) returned an unexpected response "
                "shape (missing %s) — treating as failed",
                len(payloads),
                missing,
            )
            return None
        return result

    def download_monthly_report(
        self, month: int, year: int, report_format: str = "pdf"
    ) -> bytes | None:
        try:
            r = requests.get(
                f"{self.base_url}/api/report/monthly",
                params={"month": month, "year": year, "format": report_format},
                headers=self._headers(),
                timeout=max(self.timeout, 30),
            )
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            logger.warning("Report download failed for %s-%s: %s", year, month, exc)
            return None