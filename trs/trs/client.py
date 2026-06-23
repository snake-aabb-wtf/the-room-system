"""Async Python SDK for The Room System (v3 API).

Example::

    import asyncio
    from trs import TrsClient

    async def main():
        async with TrsClient(base_url="http://127.0.0.1:8000", token="trs_xxx") as cli:
            stats = await cli.admin_stats()
            print(stats)

The client is intentionally thin: it just translates Python calls into HTTP
requests and returns parsed JSON dicts.  Pagination, file uploads and
presigned-URL downloads are exposed as small helpers on top of the same
transport.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import httpx


class TrsError(RuntimeError):
    """Raised when the server returns a non-2xx response.

    The original response and decoded JSON body (if any) are kept on
    ``.response`` / ``.body`` for callers that want richer diagnostics.
    """

    def __init__(self, message: str, *, status: int, body: Any = None, response: httpx.Response | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.response = response

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"TrsError(status={self.status}, message={self.args[0]!r})"


class TrsClient:
    """Async client for The Room System v3 API.

    Parameters
    ----------
    base_url:
        Root URL, e.g. ``http://127.0.0.1:8000``.
    token:
        API token (``trs_...``).  Mutually exclusive with ``api_key``.
    api_key:
        API key (alternative auth header).  Mutually exclusive with ``token``.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        api_key: str = "",
        room_cookie: str = "",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if token and api_key:
            raise ValueError("Pass either `token` or `api_key`, not both")
        if base_url.endswith("/"):
            base_url = base_url[:-1]
        self.base_url = base_url
        self.token = token
        self.api_key = api_key
        self.room_cookie = room_cookie
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    # ── Context manager ────────────────────────────
    async def __aenter__(self) -> "TrsClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ── Auth header helpers ────────────────────────
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        elif self.api_key:
            h["X-API-Key"] = self.api_key
        if self.room_cookie:
            # ``Cookie: room_session=...`` is needed for the few v2 endpoints
            # (file upload, messages, share) that still gate access on the
            # session cookie rather than the API token.
            h["Cookie"] = self.room_cookie
        if extra:
            h.update(extra)
        return h

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        headers = self._headers(kwargs.pop("headers", None))
        resp = await self._client.request(method, url, headers=headers, **kwargs)
        return self._handle(resp)

    @staticmethod
    def _handle(resp: httpx.Response) -> Any:
        # 204 No Content / empty body
        if resp.status_code == 204 or not resp.content:
            return None
        # Try JSON first, fall back to text for oddball responses.
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = resp.text
        if resp.status_code >= 400:
            msg = body.get("detail") if isinstance(body, dict) else None
            if not msg:
                msg = body.get("title") if isinstance(body, dict) else None
            if not msg:
                msg = (body or resp.text or "").__repr__()
            raise TrsError(f"{resp.status_code} {resp.request.method} {resp.request.url.path}: {msg}",
                           status=resp.status_code, body=body, response=resp)
        return body

    # ── Health / discovery ────────────────────────
    async def health(self) -> dict:
        return await self._request("GET", "/api/v3/admin/stats", headers={"Accept": "application/json"})

    # ── Auth tokens ───────────────────────────────
    async def list_tokens(self) -> list[dict]:
        body = await self._request("GET", "/api/v3/auth/tokens")
        return body.get("items", []) if isinstance(body, dict) else body

    async def create_token(
        self,
        name: str,
        scope: str | Iterable[str] = "user",
        *,
        room_hash: str | None = None,
        expires_at: float | None = None,
        bootstrap_password: str | None = None,
    ) -> dict:
        if isinstance(scope, (list, tuple, set)):
            scope = ",".join(scope)
        body = {
            "name": name,
            "scope": scope,
        }
        if room_hash:
            body["room_hash"] = room_hash
        if expires_at is not None:
            body["expires_at"] = expires_at
        extra: dict[str, str] = {}
        if bootstrap_password:
            extra["X-Bootstrap-Password"] = bootstrap_password
        return await self._request("POST", "/api/v3/auth/tokens", json=body, headers=extra)

    async def get_token(self, token_id: int) -> dict:
        return await self._request("GET", f"/api/v3/auth/tokens/{token_id}")

    async def patch_token(self, token_id: int, *, name: str | None = None,
                          expires_at: float | None = None) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if expires_at is not None:
            body["expires_at"] = expires_at
        return await self._request("PATCH", f"/api/v3/auth/tokens/{token_id}", json=body)

    async def revoke_token(self, token_id: int) -> None:
        await self._request("DELETE", f"/api/v3/auth/tokens/{token_id}")

    # ── Files ──────────────────────────────────────
    async def list_files(
        self,
        room: str,
        *,
        q: str = "",
        parent_dir: str | None = None,
        ext: str | Iterable[str] | None = None,
        sort: str = "time",
        page: int = 1,
        per_page: int = 50,
        include_deleted: bool = False,
    ) -> dict:
        params: dict[str, Any] = {"q": q, "sort": sort, "page": page, "per_page": per_page,
                                  "include_deleted": "true" if include_deleted else "false"}
        if parent_dir is not None:
            params["parent_dir"] = parent_dir
        if ext:
            if isinstance(ext, (list, tuple, set)):
                ext = ",".join(ext)
            params["ext"] = ext
        return await self._request("GET", f"/api/v3/rooms/{room}/files", params=params)

    async def iter_files(self, room: str, **kwargs: Any) -> AsyncIterator[dict]:
        """Iterate over every file in a room, transparently paging."""

        per_page = int(kwargs.pop("per_page", 100)) or 100
        page = int(kwargs.pop("page", 1)) or 1
        while True:
            chunk = await self.list_files(room, page=page, per_page=per_page, **kwargs)
            items = chunk.get("items", []) if isinstance(chunk, dict) else []
            for item in items:
                yield item
            pagination = chunk.get("pagination", {}) if isinstance(chunk, dict) else {}
            total_pages = int(pagination.get("total_pages", 0))
            if not items or page >= total_pages:
                return
            page += 1

    async def get_file(self, room: str, file_id: int) -> dict:
        return await self._request("GET", f"/api/v3/rooms/{room}/files/{file_id}")

    async def update_file(self, room: str, file_id: int, *,
                          name: str | None = None,
                          parent_dir: str | None = None,
                          expires_at: float | None = None) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if parent_dir is not None:
            body["parent_dir"] = parent_dir
        if expires_at is not None:
            body["expires_at"] = expires_at
        return await self._request("PATCH", f"/api/v3/rooms/{room}/files/{file_id}", json=body)

    async def delete_file(self, room: str, file_id: int) -> dict:
        return await self._request("DELETE", f"/api/v3/rooms/{room}/files/{file_id}")

    async def batch_delete(self, room: str, ids: Iterable[int]) -> dict:
        return await self._request("POST", f"/api/v3/rooms/{room}/files/batch-delete",
                                   json={"ids": list(ids)})

    async def batch_restore(self, room: str, ids: Iterable[int]) -> dict:
        return await self._request("POST", f"/api/v3/rooms/{room}/files/batch-restore",
                                   json={"ids": list(ids)})

    async def batch_purge(self, room: str, ids: Iterable[int]) -> dict:
        return await self._request("POST", f"/api/v3/rooms/{room}/files/batch-purge",
                                   json={"ids": list(ids)})

    async def list_recycle(self, room: str) -> list[dict]:
        body = await self._request("GET", f"/api/v3/rooms/{room}/recycle")
        return body.get("items", []) if isinstance(body, dict) else body

    async def empty_recycle(self, room: str) -> dict:
        return await self._request("POST", f"/api/v3/rooms/{room}/recycle/empty")

    # ── Presign / direct download ──────────────────
    async def presign(self, room: str, file_id: int, op: str = "get", ttl: int = 300) -> dict:
        return await self._request("GET", f"/api/v3/rooms/{room}/presign",
                                   params={"file_id": file_id, "op": op, "ttl": ttl})

    async def download_presigned(self, room: str, file_id: int, *,
                                 dest: str | os.PathLike[str]) -> Path:
        """Stream a file via the no-auth ``/dl_presign/...`` endpoint.

        Returns the destination :class:`pathlib.Path` for convenience.
        """
        body = await self.presign(room, file_id)
        # The presign endpoint returns a full URL with sig/exp/op query
        # params baked in; we just hit it as-is.
        url_path = body.get("url") if isinstance(body, dict) else None
        if not url_path:
            raise TrsError("presign did not return a url", status=500, body=body)
        url = f"{self.base_url}{url_path}"
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                raise TrsError(f"download failed: {resp.status_code}", status=resp.status_code,
                               body=resp.text, response=resp)
            with dest_path.open("wb") as fp:
                async for chunk in resp.aiter_bytes():
                    fp.write(chunk)
        return dest_path

    # ── Messages (room chat) ──────────────────────
    async def list_messages(self, room: str) -> list[dict]:
        return await self._request("GET", f"/api/{room}/messages")

    async def post_message(self, room: str, body: str, nick: str | None = None) -> dict:
        # The /api/{rh}/messages endpoint takes a multipart "body" field and
        # uses the nick cookie.  We don't have a cookie jar here, so the
        # caller must either be inside the room (browser cookie) or the
        # server must be configured for token-auth on this path.  For SDK
        # convenience we set an ``X-Nick`` fallback that the server accepts.
        headers: dict[str, str] = {}
        if nick:
            headers["X-Nick"] = nick
        return await self._request("POST", f"/api/{room}/messages",
                                   data={"body": body}, headers=headers)

    # ── Share links ───────────────────────────────
    async def create_share(self, room: str, *, ttl_hours: float | None = None,
                           label: str = "") -> dict:
        params: dict[str, Any] = {"label": label}
        if ttl_hours is not None:
            params["ttl"] = str(ttl_hours)
        return await self._request("POST", f"/share/{room}", params=params)

    async def list_shares(self, room: str) -> list[dict]:
        return await self._request("GET", f"/share/{room}/list")

    async def revoke_share(self, room: str, token: str) -> dict:
        return await self._request("POST", f"/share/{room}/revoke",
                                   data={"token": token})

    # ── Admin ──────────────────────────────────────
    async def admin_stats(self) -> dict:
        return await self._request("GET", "/api/v3/admin/stats")

    async def admin_rooms(self) -> list[dict]:
        body = await self._request("GET", "/api/v3/admin/rooms")
        return body.get("items", []) if isinstance(body, dict) else body

    async def admin_room(self, room: str) -> dict:
        return await self._request("GET", f"/api/v3/admin/rooms/{room}")

    async def admin_audit(self, *, page: int = 1, per_page: int = 100,
                           action: str = "", room_hash: str = "",
                           ip: str = "", since: float = 0, before: float = 0) -> dict:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if action:
            params["action"] = action
        if room_hash:
            params["room_hash"] = room_hash
        if ip:
            params["ip"] = ip
        if since:
            params["since"] = since
        if before:
            params["before"] = before
        return await self._request("GET", "/api/v3/admin/audit", params=params)

    async def admin_cleanup(self) -> dict:
        return await self._request("POST", "/api/v3/admin/cleanup")

    # ── Webhooks ───────────────────────────────────
    async def list_webhooks(self) -> list[dict]:
        body = await self._request("GET", "/api/v3/admin/webhooks")
        return body.get("items", []) if isinstance(body, dict) else body

    async def create_webhook(self, url: str, *, name: str = "webhook",
                              secret: str = "", events: list[str] | str | None = None,
                              room_hash: str | None = None) -> dict:
        body: dict[str, Any] = {"name": name, "url": url}
        if secret:
            body["secret"] = secret
        if events is not None:
            if isinstance(events, (list, tuple, set)):
                body["events"] = ",".join(events)
            else:
                body["events"] = events
        if room_hash:
            body["room_hash"] = room_hash
        return await self._request("POST", "/api/v3/admin/webhooks", json=body)

    async def get_webhook(self, webhook_id: int) -> dict:
        return await self._request("GET", f"/api/v3/admin/webhooks/{webhook_id}")

    async def patch_webhook(self, webhook_id: int, *, name: str | None = None,
                            url: str | None = None,
                            secret: str | None = None,
                            events: list[str] | str | None = None,
                            enabled: bool | None = None) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if url is not None:
            body["url"] = url
        if secret is not None:
            body["secret"] = secret
        if events is not None:
            if isinstance(events, (list, tuple, set)):
                body["events"] = ",".join(events)
            else:
                body["events"] = events
        if enabled is not None:
            # The Pydantic model uses ``active: int`` not ``enabled: bool``.
            body["active"] = 1 if enabled else 0
        return await self._request("PATCH", f"/api/v3/admin/webhooks/{webhook_id}", json=body)

    async def delete_webhook(self, webhook_id: int) -> None:
        await self._request("DELETE", f"/api/v3/admin/webhooks/{webhook_id}")

    async def webhook_deliveries(self, webhook_id: int) -> list[dict]:
        body = await self._request("GET", f"/api/v3/admin/webhooks/{webhook_id}/deliveries")
        return body.get("items", []) if isinstance(body, dict) else body
