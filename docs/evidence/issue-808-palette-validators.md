# Issue #808: palette-aware feed validators

The image ETag includes the ordered RGB colours and measured flag of the palette used by the response. Existing master mtime, effective fit, target, dither and selected render strategy remain inputs. Palette names and provenance notes do not identify pixels or measurement metadata.

Both `/feed/{id}/current` and `/feed/{id}/image/0` exercise two separate controls:

- Changed RGB colours: the prior validator returns HTTP 200 with a different ETag and different decoded pixels from the replacement palette; the new validator returns HTTP 304.
- Changed measurement flag alone: the prior validator returns HTTP 200 with a different ETag and updated `X-Palette-Measured`; decoded pixels are unchanged and the new validator returns HTTP 304.

These cases also pin unchanged strategy, master mtime and Cache-Control. Unchanged palettes produce stable validators; a unit case verifies order is significant.

## Executed software checks (2026-10-23 UTC)

Commands used the isolated worktree `.venv/bin/python` (Python 3.12), with dependencies from the repository's declared dev extra. No hardware or physical calibration acceptance is implied.

```sh
.venv/bin/python -m pytest -p no:cov -o addopts= tests/test_eink_feed_endpoints.py -q -k 'feed_etag_tracks_ordered_palette_and_measurement_only or palette_change_revalidates_feed_image'
# Unmodified implementation: 5 passed, 90 deselected.
# Disconnect palette_identity from the production item_etag hash input:
# 5 failed, 90 deselected (one unit control and all four HTTP controls).
# Restore the exact source bytes and repeat: 5 passed, 90 deselected.

.venv/bin/python -m pytest -p no:cov -o addopts= tests/test_eink_feed_endpoints.py -q
# 95 passed.
```

The deliberately broken implementation retained the existing validator inputs and replaced only the `|palette-v1|{palette_identity}` hash component with `|palette-v1`. All five regressions detected this missing input. The restored `src/fine_art_archive/eink/feed.py` SHA-256 is `24c0c87f63271d68080419cbe554761adf8725af19728c804bc6b84ed305c818`.

Hosted current-head CI, review and post-merge verification remain separate delivery gates.
