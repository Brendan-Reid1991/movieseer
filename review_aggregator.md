# Aggregator Package Review

Scope: `movieseer/aggregator/` and all subpackages.

---

## Bugs

### 1. TV queue enrichment skips warning/error detection in `_build_js_item`

`_build_direct_series_item` was fixed to use `**_arr_queue_status(queue_items[0])`, but the identical branch in `_build_js_item` (line 227) was not:

```python
# current — hardcoded, no warning/error detection
item["arr"] = {
    "status": "downloading",
    "episodes_queued": len(queue_items),
    "error": None,
}

# should be
item["arr"] = {
    **_arr_queue_status(queue_items[0]),
    "episodes_queued": len(queue_items),
}
```

Jellyseerr-sourced TV downloads with a Sonarr warning or error are silently presented as `"downloading"`.

---

### 2. `_js_status` doesn't handle request status 4 (COMPLETED)

The Jellyseerr `MediaRequestStatus` enum has four values: 1 PENDING, 2 APPROVED, 3 DECLINED, 4 COMPLETED. The mapping only covers 1–3:

```python
return {1: "pending", 2: "approved", 3: "declined"}.get(req_status, "unknown")
```

A completed request (status 4) returns `"unknown"`. Should map to `"completed"` (or `"available"`, depending on what the frontend expects — but `"unknown"` is wrong either way).

---

### 3. `asyncio` imported inside a method body in `sabnzbd.py`

`server_stats()` has `import asyncio` at line 101 inside the method. It should be at the top of the file. This is harmless at runtime (Python caches module imports) but is surprising and inconsistent.

---

## Design Issues

### 4. `DownloadInfo` is dead code

`RequestItem.download` is `DownloadInfo | None` and is set to `None` in every code path. `DownloadInfo` itself is fully defined with five fields. Either the feature was planned but not implemented, or it was removed and the type/field were left behind. It should be deleted or filed as a known gap — having a field that's always `None` misleads any consumer reading the schema.

### 5. `_build_js_item` enrichment is serial

When a Jellyseerr request has an `arr_id` but is not in the queue (the fallback path), the method makes two sequential API calls:

```python
movie = await self._radarr.movie(arr_id)       # call 1
history = await self._radarr.movie_history(arr_id)  # call 2
```

With N such requests, this is 2N sequential HTTP round-trips. They could be gathered:

```python
movie, history = await asyncio.gather(
    self._radarr.movie(arr_id),
    self._radarr.movie_history(arr_id),
)
```

Same applies to the Sonarr path.

### 6. Cache has no concurrency guard

Two concurrent calls to `get_status()` that both see a stale cache will both fetch and both write. In the current single-worker deployment this is benign, but it's worth noting if the app ever runs with concurrency > 1. A simple `asyncio.Lock` on the fetch would fix it.

### 7. `SystemStatus` couples the types module to service modules

`types.py` imports `ProwlarrStatus`, `Queue`, and `Torrent` directly from service modules. This means a service-layer type change forces a change in the shared types module. The error union (`ProwlarrStatus | dict[str, str]`) is also awkward — consumers must `isinstance`-check before using the value, and the `dict[str, str]` form only carries `"error"` but has no type constraint enforcing that. A dedicated `ErrorResult` TypedDict or a discriminated union would be cleaner.

### 8. `QBittorrentClient` logs in before every request

The `_login()` call is made unconditionally before `summary()` and `torrents()`, so every poll cycle makes two HTTP requests to qBittorrent regardless of session state. The docstring acknowledges this but calls it "pre-existing behaviour". It's a straightforward improvement: login once at startup, retry on 403/Forbidden.

---

## Type System Issues

### 9. `RequestItem.type` and `RequestItem.source` typed as `str`

Both fields have a fixed set of values in practice:
- `type`: `"movie"` or `"tv"`
- `source`: `"jellyseerr"`, `"radarr"`, or `"sonarr"`

Typing them as `str` loses that information. They should be `Literal["movie", "tv"]` and `Literal["jellyseerr", "radarr", "sonarr"]` respectively.

### 10. `MediaInfo.status` has no default

Jellyseerr's `Media` entity defaults to `status = 1` (UNKNOWN) in the database, but the Pydantic model declares `status: int` with no default. If the API ever omits it (or a future endpoint doesn't include the full media object), validation will fail. Safer as `status: int = 1`.

### 11. `MediaRequest.created_at` is `str`, not `datetime`

Radarr and Sonarr models parse timestamps into `datetime` objects via Pydantic. Jellyseerr's `created_at` comes through as a raw ISO 8601 string. This inconsistency means callers get different types depending on source — the sort key in `_get_requests` does string comparison on `created_at` against `arr.at` (also a string), which happens to work but is fragile.

### 12. `_BaseServiceClient._get` return type forces `type: ignore` at call sites

The return type `dict[str, object] | list[object]` is correct (JSON can be either), but every caller that expects a specific shape has to either cast or use `# type: ignore[index]`. This is visible in `radarr.py`, `sonarr.py`, and `prowlarr.py`. A typed subclass or generic return wouldn't fully solve it, but the `type: ignore` comments indicate a known gap worth tracking.

---

## Minor Observations

### 13. `req: MediaRequest` pre-declaration in `_get_requests` (line 148)

```python
req: MediaRequest
for req in js_requests:
```

This is a workaround to help the type checker treat `req` as `MediaRequest` inside the loop, because `js_requests` is typed as `list[MediaRequest] | Exception` before the `isinstance` guard. It works but is unusual — the cleaner fix is to narrow the type before the loop:

```python
requests: list[MediaRequest] = js_requests  # after the isinstance guard
for req in requests:
```

### 14. `_is_recent` has an implicit UTC assumption

`dt.replace(tzinfo=dt.tzinfo or UTC)` assumes naive datetimes are UTC. Radarr and Sonarr do return UTC timestamps, but this is an undocumented assumption. A comment stating it, or an assertion, would help a future reader.

### 15. Sort mixes `requested_at` and `arr.at` as if they're comparable

```python
key=lambda item: item.get("requested_at") or (item.get("arr") or {}).get("at") or ""
```

`requested_at` is the Jellyseerr request timestamp; `arr.at` is the most recent Radarr/Sonarr history event timestamp. For direct items (no Jellyseerr request), these are different concepts being compared as if interchangeable. The sort produces a "roughly newest first" result, which is probably good enough for a dashboard, but it can surface a recently-grabbed direct item above an older Jellyseerr request even if the Jellyseerr request was newer.

### 16. `_Base` missing `from __future__ import annotations`

All other model files use the `from __future__ import annotations` import for deferred evaluation. `_base.py` doesn't, which is inconsistent. Not a bug today, but matters if forward references are ever added.
