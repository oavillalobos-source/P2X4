"""Small server-side client for the authenticated P2X4 docking bridge."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class P2X4APIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class P2X4API:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://127.0.0.1"):
            raise ValueError("The docking API must use HTTPS (localhost is allowed for development)")
        if not self.token:
            raise ValueError("The docking API token is empty")

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "P2X4-Streamlit-Bridge/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error = {}
            raise P2X4APIError(
                str(error.get("error") or f"Docking API returned HTTP {exc.code}"),
                status=exc.code,
                code=error.get("code"),
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise P2X4APIError(f"Docking API is unavailable: {exc.reason if isinstance(exc, URLError) else exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/api/v1/health")

    def submit_job(self, compound_id: str, smiles: str, allow_duplicate: bool = False) -> dict[str, Any]:
        return self._json(
            "POST",
            "/api/v1/jobs",
            {"compound_id": compound_id, "smiles": smiles, "allow_duplicate": allow_duplicate},
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/jobs/{job_id}")

    def job_result(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/api/v1/jobs/{job_id}/result")
