# Companion App API Audit

Scope audited:

- `src/fine_art_archive/api/main.py`
- `src/fine_art_archive/api/store.py`
- `src/fine_art_archive/collect/acquisition_flow.py`
- `tests/test_companion_app_api.py`
- `scripts/run_companion_app.sh`
- `scripts/api_client.py`

I did not inspect `src/fine_art_archive/ui/index.html` because it was outside the explicit "Audit ONLY" file list. That means I can enumerate the API routes and references in the audited files, but I cannot fully prove whether the browser UI's inline JS references only defined routes. Confidence in route definition/wiring findings below is high; confidence in UI/JS route parity is intentionally limited by scope.

Verification performed:

- `PYTHONPATH=src python - <<'PY' ... app.routes ... PY` enumerated the registered FastAPI routes.
- `python -m pytest tests/test_companion_app_api.py` ran 15 endpoint tests; all test cases passed, but the command failed the repo-wide coverage gate (`total of 9 is less than fail-under=25`).
- `PYTHONPATH=src python -m pytest tests/test_companion_app_api.py --no-cov` passed: 15 passed.

## Endpoint Inventory

FastAPI's default docs routes are enabled:

| Method | Path | Reads | Writes |
|---|---|---|---|
| GET/HEAD | `/openapi.json` | generated OpenAPI schema | none |
| GET/HEAD | `/docs` | generated Swagger UI | none |
| GET/HEAD | `/docs/oauth2-redirect` | generated Swagger helper | none |
| GET/HEAD | `/redoc` | generated ReDoc UI | none |

Application routes:

| Method | Path | Handler | Reads | Writes |
|---|---|---|---|---|
| GET | `/` | `root` | `UI_FILE` (`src/fine_art_archive/ui/index.html`) | none |
| GET | `/healthz` | `healthz` | `store.load_manifest()`, `store.count_ratings()` | none |
| GET | `/works` | `list_works` | `manifest.csv`, ratings log cache/log, artist alias table | none |
| GET | `/works/{work_id}` | `get_work` | `staging_sidecars/{work_id}/meta.json`, ratings log | none |
| GET | `/artists` | `list_artists` | `manifest.csv`, artist alias table | none |
| GET | `/queues` | `list_queues` | `data/queues/*.json` | none |
| GET | `/queues/{name}` | `get_queue` | `data/queues/{name}.json`, sidecars, ratings log | none |
| POST | `/works/{work_id}/subject_action` | `subject_action` | sidecar `meta.json` | appends `data/subject_tag_events.jsonl`; rewrites sidecar `meta.json` |
| GET | `/works/{work_id}/image` | `work_image` | hardcoded art workspace master or sidecar fallback | writes resized JPEG cache under `data/image_cache` on miss |
| GET | `/works/{work_id}/full` | `work_full` | hardcoded art workspace master or sidecar fallback | none |
| GET | `/rating_taxonomy` | `rating_taxonomy` | in-memory `RATING_TAXONOMY` | none |
| POST | `/works/{work_id}/rate` | `rate_work` | sidecar existence check | appends `data/ratings_log.jsonl`; invalidates in-process ratings cache |
| POST | `/debug/log` | `debug_log` | request body | appends `automation_logs/ui_debug.log` |
| GET | `/works/{work_id}/ratings` | `work_ratings` | ratings log/cache | none |
| GET | `/ratings/recent` | `recent_ratings` | ratings log/cache | none |
| GET | `/ratings/summary` | `ratings_summary` | ratings log/cache | none |
| GET | `/variant_upgrades` | `variant_upgrades` | `variant_upgrade_candidates.csv`, `data/variant_upgrade_decisions.jsonl` | none |
| POST | `/variant_upgrades/{existing_wid}/decision` | `variant_upgrade_decision` | request body only | appends `data/variant_upgrade_decisions.jsonl` |

No application route is defined-but-unreachable in FastAPI's route table. The `/works/{work_id}` route does not shadow `/works/{work_id}/image`, `/full`, or `/ratings` because Starlette requires a full path match for each route. `POST /works/{work_id}/rate` now has CI coverage in `tests/test_companion_app_api.py:99-123`, so prior issue #98 appears addressed for the happy write path. That coverage is narrow: it stubs `store.get_work`, uses an isolated log path, and does not exercise corrupt logs, concurrent writes, multiprocess caches, malformed floats, or actual sidecar lookup.

`scripts/api_client.py` is a GitHub API client, not a Companion App client. It does not reference or validate any Companion App route.

## Findings

### 1. [MAJOR] `work_id` is used as a filesystem path segment without containment checks

Code:

```python
# src/fine_art_archive/api/store.py:118-123
def get_work(work_id: str) -> dict | None:
    sidecar_path = STAGING / work_id / "meta.json"
    if not sidecar_path.exists():
        return None
    with open(sidecar_path) as f:
        return json.load(f)
```

```python
# src/fine_art_archive/api/main.py:190-193
sc_path = store.STAGING / work_id / "meta.json"
if not sc_path.exists():
    raise HTTPException(404, f"no sidecar for {work_id}")
sc = json.loads(sc_path.read_text())
```

Why it is a problem:

`work_id` is trusted as a directory name. Encoded `..` reaches the handler (`GET /works/%2E%2E` returns a sidecar-specific 404, not a route 404), and `store.STAGING / ".." / "meta.json"` resolves to `REPO_ROOT/meta.json`. The same pattern exists for image lookup at `ART_WORKS_ROOT / work_id` in `src/fine_art_archive/api/main.py:296`. If a matching sibling/root `meta.json` or `master.*` exists, the API can read or mutate outside the intended sidecar/work tree. The mutating `subject_action` path is the highest-risk use because it can rewrite the resolved file.

Repro:

```bash
PYTHONPATH=src python - <<'PY'
from fine_art_archive.api import store
print((store.STAGING / ".." / "meta.json").resolve())
PY
```

Existing tests would NOT catch this. They test `"/works/nonexistent-wid"` and `"/works/no-such-wid/rate"` only, not encoded dot segments or path containment.

One-line fix:

Validate `work_id` against the manifest/known ID regex and reject `.`, `..`, slashes, backslashes, and path separators; also resolve candidate paths and require `candidate.is_relative_to(STAGING)` or `ART_WORKS_ROOT`.

Confidence: high. I would change this only if upstream routing were proven to reject all encoded dot segments before the handler, but current `TestClient` evidence shows `%2E%2E` reaches the handler.

### 2. [MAJOR] `POST /rate` accepts malformed float input and can persist non-standard JSON

Code:

```python
# src/fine_art_archive/api/main.py:520-523
dwell_seconds: float | None = Field(
    default=None,
    description="Seconds on the work before rating (signal, not ground truth)",
)
```

```python
# src/fine_art_archive/api/main.py:569, 576-577
"dwell_seconds": body.dwell_seconds,
...
with open(RATINGS_LOG, "a") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")
```

Why it is a problem:

`dwell_seconds` has no lower bound and does not forbid NaN/Infinity. Pydantic coerces strings such as `"NaN"` into a float NaN, and Python's `json.dumps` writes that as `NaN`, which is not valid JSON for strict downstream parsers. Negative dwell time is also accepted. Pydantic's default coercion also accepts `"5"` for integer rating axes, so wrong-type JSON can become stored data instead of a 422.

Repro:

```bash
PYTHONPATH=src python - <<'PY'
from fastapi.testclient import TestClient
from fine_art_archive.api.main import app
from fine_art_archive.api import store
store.get_work = lambda _wid: {"work_id": _wid}
client = TestClient(app, raise_server_exceptions=False)
print(client.post("/works/test/rate", json={"quality": 5, "dwell_seconds": "NaN"}).status_code)
print(client.post("/works/test/rate", json={"quality": 5, "dwell_seconds": -1}).status_code)
PY
```

Existing tests would NOT catch this. They cover out-of-range `rating`, unknown surface, unknown chip IDs, and all-null payloads, but not float NaN/Infinity, negative dwell time, or strict type behavior.

One-line fix:

Use strict constrained types, for example `dwell_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)` and strict integer validation for rating axes; write logs with `json.dumps(..., allow_nan=False)`.

Confidence: high. The only uncertainty is whether the intended model wants to allow negative dwell as a sentinel; the code and field description do not document that.

### 3. [MAJOR] Ratings cache invalidation is process-local, so multiple workers can serve stale data after writes

Code:

```python
# src/fine_art_archive/api/store.py:167-176
_RATINGS_CACHE: list[dict] | None = None
_RATINGS_BY_WORK: dict[str, list[dict]] | None = None

def _load_ratings() -> list[dict]:
    global _RATINGS_CACHE
    if _RATINGS_CACHE is not None:
        return _RATINGS_CACHE
```

```python
# src/fine_art_archive/api/main.py:575-579
RATINGS_LOG.parent.mkdir(parents=True, exist_ok=True)
with open(RATINGS_LOG, "a") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")
store.invalidate_ratings_cache()
return {"ok": True, "event": event, "total_ratings_for_work": store.count_ratings_for(work_id)}
```

Why it is a problem:

The ratings store is a file plus process-local globals. `POST /rate` invalidates only the current Python process. If the app is launched with multiple uvicorn workers or another process writes the sanctioned operational log, `GET /works`, `/ratings/recent`, `/ratings/summary`, and `/works/{work_id}/ratings` can keep serving stale cached ratings indefinitely in other processes. There is no file mtime check, shared cache invalidation, or reload-on-read strategy.

Repro:

1. Start the app with two workers.
2. Prime `/ratings/summary` through worker A.
3. Submit `POST /works/{work_id}/rate` through worker B.
4. Repeat `/ratings/summary`; worker A can return the pre-write cache.

Existing tests would NOT catch this. `TestClient` is single-process and all cache invalidation happens in the same interpreter.

One-line fix:

Make ratings reads reload when `RATINGS_LOG.stat().st_mtime_ns` or size changes, or move persistence to a transactional store with shared visibility; document/support only one worker if that is the actual contract.

Confidence: high for multi-process staleness. I would downgrade if `run_companion_app.sh` or deployment docs explicitly forbid multiple workers and external writers.

### 4. [MAJOR] Corrupt rating log lines are silently dropped and health still reports success

Code:

```python
# src/fine_art_archive/api/store.py:178-187
if RATINGS_LOG.exists():
    with open(RATINGS_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
```

Why it is a problem:

If `data/ratings_log.jsonl` is partially written, hand-edited incorrectly, or corrupted, the store silently skips the bad line. Every read endpoint then returns 200 with a reduced event set. Because `/healthz` uses `store.count_ratings()`, it also reports `"ok": true` against silently truncated logical data. This papers over exactly the operational data failure the sanctioned bridge should make loud.

Repro:

```bash
printf '{"work_id":"a","rating":1}\nnot-json\n' > /tmp/ratings_log.jsonl
# monkeypatch store.RATINGS_LOG to /tmp/ratings_log.jsonl, invalidate cache,
# then call /healthz or /ratings/summary: the bad line is ignored.
```

Existing tests would NOT catch this. They test an empty store and one valid append only.

One-line fix:

Fail closed on malformed log lines: record line number and return a 503/health failure, or quarantine corrupt lines while preserving an explicit error count in every ratings response.

Confidence: high. The only valid counterargument would be an explicit product requirement to tolerate corrupt append logs by losing events, and that requirement is not present in the audited files.

### 5. [MAJOR] `subject_action` records audit events before validating that the mutation can succeed

Code:

```python
# src/fine_art_archive/api/main.py:195-206
# Audit event (always written)
event = {
    "ts": _now(),
    "work_id": work_id,
    "action": body.action,
    "tag": body.tag or None,
    "text": body.text or None,
    "reviewer": body.reviewer,
}
SUBJECT_TAG_EVENTS.parent.mkdir(parents=True, exist_ok=True)
with open(SUBJECT_TAG_EVENTS, "a") as f:
    f.write(json.dumps(event, ensure_ascii=False) + "\n")
```

```python
# src/fine_art_archive/api/main.py:216-218
# Tag-mutation actions
if not body.tag or ":" not in body.tag:
    raise HTTPException(400, "tag required (format 'group:id')")
```

Why it is a problem:

For `confirm`, `reject`, `add`, and `reset`, the endpoint appends an audit event before it checks whether `tag` is present and valid. A request can return 400 while still writing a durable "confirm/reject/add/reset" event. That is a false audit trail and an endpoint with a side effect on failure.

Repro:

```bash
curl -s -X POST http://127.0.0.1:8401/works/<existing-work>/subject_action \
  -H 'content-type: application/json' \
  -d '{"action":"confirm","tag":""}'
# Response: 400. data/subject_tag_events.jsonl still receives the event.
```

Existing tests would NOT catch this. `tests/test_companion_app_api.py` has no `subject_action` coverage.

One-line fix:

Validate action-specific preconditions before writing the event, or write explicit failed-attempt events with `"ok": false` and do not mix them with successful audit history.

Confidence: high. The code comment says "always written", but that behavior is incompatible with a successful-action audit log unless failures are clearly labeled.

### 6. [MAJOR] Sidecar mutations are read-modify-write without locking or atomic replace

Code:

```python
# src/fine_art_archive/api/main.py:193, 213
sc = json.loads(sc_path.read_text())
...
sc_path.write_text(json.dumps(sc, indent=2, ensure_ascii=False))
```

```python
# src/fine_art_archive/api/main.py:281-283
# Recompute needs_review
subj["needs_review"] = any(t.get("state") == "proposed" for t in tags)
sc_path.write_text(json.dumps(sc, indent=2, ensure_ascii=False))
```

Why it is a problem:

Two concurrent reviewer actions against the same work can both read the same sidecar, apply different changes, and then the later `write_text` overwrites the earlier update. A crash during `write_text` can also leave a truncated or partially written `meta.json`. The store has no schema/version guard, no etag/revision check, no file lock, and no atomic temp-file replace.

Repro:

1. Fire two `POST /works/{same_work}/subject_action` requests in parallel for different tags.
2. Both can return `{"ok": true}`.
3. Only the last writer's mutation is guaranteed to survive in `meta.json`.

Existing tests would NOT catch this. There are no sidecar mutation tests and no concurrent request tests.

One-line fix:

Serialize sidecar writes with an advisory lock and write to a temp file followed by `os.replace`; optionally include a sidecar schema version/revision and reject stale writes.

Confidence: high. The standard filesystem race applies directly to the shown read-modify-write pattern.

### 7. [MAJOR] Store paths are hardcoded, including an operator-specific absolute art workspace

Code:

```python
# src/fine_art_archive/api/main.py:20-28
REPO_ROOT = Path(__file__).resolve().parents[3]
UI_FILE = REPO_ROOT / "src" / "fine_art_archive" / "ui" / "index.html"
RATINGS_LOG = REPO_ROOT / "data" / "ratings_log.jsonl"
...
ART_WORKS_ROOT = Path("/Users/teacher/Library/CloudStorage/Dropbox/Pictures/Art/works")
IMAGE_CACHE_DIR = REPO_ROOT / "data" / "image_cache"
```

```python
# src/fine_art_archive/api/store.py:18-21
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "staging_sidecars"
MANIFEST_CSV = REPO_ROOT / "manifest.csv"
RATINGS_LOG = REPO_ROOT / "data" / "ratings_log.jsonl"
```

Why it is a problem:

The README context says this app is the sanctioned bridge between repo code and the operational data workspace, but the store path is split between repo-relative files and a single user-specific absolute Dropbox path. `scripts/run_companion_app.sh` exposes only host and port configuration, not the archive/store roots. This makes the app brittle across clones, CI, and alternate operators, and it pushes tests into monkeypatching module globals instead of exercising supported configuration.

Repro:

Run the app on any machine that does not have `/Users/teacher/Library/CloudStorage/Dropbox/Pictures/Art/works`; image/full endpoints cannot serve promoted masters even when a valid archive root exists elsewhere.

Existing tests would NOT catch this. They do not call `/works/{work_id}/image` or `/works/{work_id}/full`, and they monkeypatch only ratings log paths for `/rate`.

One-line fix:

Introduce a single settings object populated from environment variables such as `FAA_STAGING_DIR`, `FAA_MANIFEST_CSV`, `FAA_RATINGS_LOG`, `FAA_ART_WORKS_ROOT`, and `FAA_IMAGE_CACHE_DIR`; have the launcher document them.

Confidence: high. I would soften this only if the app is intentionally single-user and never expected to run outside this exact account path, but that should be stated explicitly.

### 8. [MAJOR] `/ratings/summary` still summarizes only the deprecated single-axis `rating`

Code:

```python
# src/fine_art_archive/api/store.py:235-248
def ratings_summary() -> dict:
    events = _load_ratings()
    dist = Counter(e.get("rating") for e in events if e.get("rating") is not None)
    by_surface = Counter(e.get("surface") for e in events)
    by_work = _ratings_by_work()
    return {
        "n_events": len(events),
        "n_works_rated": len(by_work),
        "rating_distribution": {str(k): dist[k] for k in sorted(dist)},  # type: ignore[type-var]
        "by_surface": dict(by_surface),
        "most_rated_works": [
            {"work_id": w, "n_ratings": len(evs), "last_rating": evs[-1]["rating"]}
            for w, evs in sorted(by_work.items(), key=lambda kv: -len(kv[1]))[:10]
        ],
    }
```

Why it is a problem:

The current request model and tests use the two-axis scheme (`quality` and `fit`), while `rating` is documented as deprecated. The summary endpoint reports distribution only for non-null legacy `rating` and `most_rated_works.last_rating` from `evs[-1]["rating"]`. For current valid `/rate` submissions, the endpoint can report `n_events > 0` while `rating_distribution` is empty and `last_rating` is `None`. That is a correctness bug in a read API, not just a missing feature.

Repro:

1. Submit a valid current rating: `{"quality": 8, "fit": 6}`.
2. Call `/ratings/summary`.
3. The event count increases, but the distribution does not reflect `quality` or `fit`.

Existing tests would NOT catch this. The write-path test asserts the event payload and file append, but it never calls `/ratings/summary` after a two-axis write.

One-line fix:

Return separate `quality_distribution` and `fit_distribution`, keep `rating_distribution` only as legacy, and expose latest `quality`/`fit` beside legacy `last_rating`.

Confidence: high. The code comments in `RatingIn` explicitly say new UI submissions should send `quality + fit`.

### 9. [MINOR] Queue corruption is hidden in list view but crashes detail view

Code:

```python
# src/fine_art_archive/api/main.py:111-123
for p in sorted(QUEUES_DIR.glob("*.json")):
    try:
        q = json.loads(p.read_text())
        out.append(...)
    except json.JSONDecodeError:
        continue
return {"queues": out}
```

```python
# src/fine_art_archive/api/main.py:133-137
p = QUEUES_DIR / f"{name}.json"
if not p.exists():
    raise HTTPException(404, f"no queue named {name!r}")
q = json.loads(p.read_text())
```

Why it is a problem:

`GET /queues` silently drops invalid queue files and returns 200, while `GET /queues/{name}` raises an unhandled `JSONDecodeError` and returns a 500 for the same corrupted file. Operators get neither a health failure nor a stable error shape identifying the bad queue.

Repro:

Create `data/queues/bad.json` containing `{bad`. `GET /queues` omits it with 200; `GET /queues/bad` 500s.

Existing tests would NOT catch this. The queue test only asserts that `/queues` returns a body with `"queues"`.

One-line fix:

Validate queue JSON through a Pydantic model and return a consistent 422/503 with filename and parse error, while surfacing invalid queue count in `/healthz`.

Confidence: high.

### 10. [MINOR] Variant-upgrade decisions can be recorded for arbitrary IDs

Code:

```python
# src/fine_art_archive/api/main.py:655-667
@app.post("/variant_upgrades/{existing_wid}/decision")
def variant_upgrade_decision(existing_wid: str, body: UpgradeDecisionIn) -> dict:
    if body.decision not in {"accept", "reject", "defer"}:
        raise HTTPException(400, "decision must be accept/reject/defer")
    event = {
        "existing_wid": existing_wid,
        "decision": body.decision,
        "note": body.note or None,
        "ts": _now(),
    }
    VARIANT_UPGRADE_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(VARIANT_UPGRADE_DECISIONS, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
```

Why it is a problem:

The endpoint does not verify that `existing_wid` exists in `variant_upgrade_candidates.csv`, in the manifest, or as a sidecar. A typo or stale browser state can append durable promotion-review decisions for nonexistent works. Since the "accept" path is meant to precede a separately gated promotion, bad IDs in this log can confuse later automation.

Repro:

```bash
curl -s -X POST http://127.0.0.1:8401/variant_upgrades/not-a-real-work/decision \
  -H 'content-type: application/json' \
  -d '{"decision":"accept","note":"typo"}'
# Returns ok and appends the decision.
```

Existing tests would NOT catch this. There is no `variant_upgrades` route coverage.

One-line fix:

Load the candidate set and reject decisions whose `existing_wid` is not present; optionally also require `store.get_work(existing_wid)` to exist.

Confidence: high.

## Coverage Gaps That Matter

- `POST /rate` happy-path persistence is now covered by `tests/test_companion_app_api.py:99-123`; issue #98's narrow concern appears fixed.
- No tests cover `/works/{work_id}/image`, `/works/{work_id}/full`, `/works/{work_id}/subject_action`, `/debug/log`, `/ratings/recent`, `/variant_upgrades`, or `/variant_upgrades/{existing_wid}/decision`.
- No tests exercise corrupt JSONL, corrupt queues, corrupt sidecars, multiprocess cache staleness, concurrent writes, filesystem write failures, NaN/Infinity floats, or path containment.
- The default test command currently fails coverage despite all `test_companion_app_api.py` tests passing. That is a CI-signal issue separate from endpoint behavior.

