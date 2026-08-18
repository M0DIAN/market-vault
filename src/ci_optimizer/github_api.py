"""Read-only GitHub REST API adapter.

Required permissions for the reusable workflow are minimal:
``contents: read``, ``pull-requests: read``, ``actions: read``. Proof
logic never requests write permission.

Token handling:
- never logged
- sent only to ``api.github.com``
- stripped on cross-host redirect (the signed artifact CDN URL needs
  no token)

Network / API failures raise ``APIError`` with a specific fail-closed
reason; the verifier converts every one of them to ``reuse=false``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

USER_AGENT = "ci-optimizer-post-merge-reuse"
API_BASE = "https://api.github.com"


class APIError(Exception):
    """A GitHub API failure with a specific fail-closed reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoTokenRedirect(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's artifact 302 to the CDN without forwarding the
    Bearer token (the signed CDN URL needs none)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and new.host != req.host:
            new.remove_header("Authorization")
        return new


def _default_urlopen() -> Callable[..., Any]:
    opener = urllib.request.build_opener(_NoTokenRedirect())
    return opener.open


class GitHubAPI:
    """Read-only GitHub REST client. ``urlopen`` is injectable for
    offline tests."""

    def __init__(
        self,
        repository: str,
        token: str,
        *,
        urlopen: Callable[..., Any] | None = None,
        timeout: int = 30,
    ):
        self.repository = repository
        self.token = token
        self._urlopen = urlopen if urlopen is not None else _default_urlopen()
        self.timeout = timeout

    # -- low-level ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }

    def _get(self, url: str) -> tuple[int, bytes, Any]:
        request = urllib.request.Request(url, headers=self._headers())
        try:
            response = self._urlopen(request, timeout=self.timeout)
            return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers
        except (urllib.error.URLError, TimeoutError):
            raise APIError("network_error")

    def _api_url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    @staticmethod
    def _next_page_url(link_header: str) -> str | None:
        for part in link_header.split(","):
            url, _, rel = part.partition(";")
            if 'rel="next"' in rel:
                return url.strip().strip("<>")
        return None

    def _get_list_json(
        self,
        path: str,
        params: dict[str, str] | None,
        key: str | None,
        max_pages: int = 10,
    ) -> list[dict]:
        items: list[dict] = []
        url = self._api_url(path, params)
        for _ in range(max_pages):
            status, body, headers = self._get(url)
            if status == 404:
                raise APIError("api_http_error_404")
            if not 200 <= status < 300:
                raise APIError(f"api_http_error_{status}")
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise APIError("malformed_api_response")
            if key is None:
                if not isinstance(data, list):
                    raise APIError("malformed_api_response")
                batch = data
            else:
                if not isinstance(data, dict) or not isinstance(data.get(key), list):
                    raise APIError("malformed_api_response")
                batch = data[key]
            items.extend(batch)
            next_url = self._next_page_url(str(headers.get("Link", "")))
            if not next_url:
                return items
            url = next_url
        raise APIError("api_pagination_limit")

    def _download_bytes(self, path: str) -> bytes:
        status, body, _ = self._get(self._api_url(path))
        if status == 404:
            raise APIError("attestation_artifact_download_failed")
        if not 200 <= status < 300:
            raise APIError(f"api_http_error_{status}")
        return body

    # -- queries -----------------------------------------------------------

    def list_pulls_for_commit(self, commit_sha: str) -> list[dict]:
        """GET /repos/{owner}/{repo}/commits/{sha}/pulls (read-only)."""
        return self._get_list_json(
            f"/repos/{self.repository}/commits/{commit_sha}/pulls", None, None
        )

    def list_runs_for_head(self, head_sha: str) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs?event=pull_request&head_sha=..."""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs",
            {"event": "pull_request", "head_sha": head_sha, "per_page": "100"},
            "workflow_runs",
        )

    def list_jobs(self, run_id: int) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs/{id}/jobs"""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs/{run_id}/jobs",
            {"per_page": "100"},
            "jobs",
        )

    def list_artifacts(self, run_id: int) -> list[dict]:
        """GET /repos/{owner}/{repo}/actions/runs/{id}/artifacts"""
        return self._get_list_json(
            f"/repos/{self.repository}/actions/runs/{run_id}/artifacts",
            {"per_page": "100"},
            "artifacts",
        )

    def download_artifact(self, artifact_id: int) -> bytes:
        """GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip (follows
        the 302 to the signed CDN URL without the token)."""
        return self._download_bytes(
            f"/repos/{self.repository}/actions/artifacts/{artifact_id}/zip"
        )
