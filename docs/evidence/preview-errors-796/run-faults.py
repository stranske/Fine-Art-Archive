import hashlib
import json
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[3]
p = root / "src/fine_art_archive/api/main.py"
original = p.read_bytes()
s = original.decode()
start = s.index('@app.get("/works/{work_id}/eink_preview")')
end = s.index("\n@app.", start + 1)
section = s[start:end]
out = root / "docs/evidence/preview-errors-796"
rows = []
base = "tests/test_eink_monochrome_delivery.py::"
call = '_eink.render_for_target(__import__("PIL.Image", fromlist=["Image"]).new("RGB", (8, 8)), _eink.RenderTarget("fault", "fault", 8, 8, "spectra6"), method="none")'
cases = [
    (
        "invalid-target",
        "tgt = _eink.get_target(target)",
        'tgt = _eink.get_target("test-strategy")',
        base + "test_preview_rejects_invalid_render_options_before_rendering",
        "query0",
        1,
    ),
    (
        "invalid-dither",
        'if dither not in ("none", "floyd-steinberg", "atkinson"):',
        "if False:",
        base + "test_preview_rejects_invalid_render_options_before_rendering",
        "query1",
        1,
    ),
    (
        "invalid-fit",
        "render_fit = _eink.coerce_fit(fit)",
        "render_fit = None",
        base + "test_preview_rejects_invalid_render_options_before_rendering",
        "query2",
        1,
    ),
    (
        "missing-master",
        'raise HTTPException(404, f"no local master for {work_id}")',
        'raise HTTPException(410, f"no local master for {work_id}")',
        base + "test_preview_reports_missing_master_before_attempting_a_render",
        "",
        1,
    ),
    (
        "render-error",
        'raise HTTPException(500, f"render failed: {exc}")',
        'raise HTTPException(400, f"render failed: {exc}")',
        base + "test_preview_turns_render_failures_into_a_clear_server_error",
        "",
        1,
    ),
    (
        "invalid-options-order",
        "    master = _eink_master(work_id)",
        "    " + call + "\n    master = _eink_master(work_id)",
        base + "test_preview_rejects_invalid_render_options_before_rendering",
        "",
        3,
    ),
    (
        "invalid-diagnostics",
        "    except KeyError as exc:\n        raise HTTPException(400, str(exc)) from exc\n    except ValueError as exc:\n        raise HTTPException(400, str(exc)) from exc",
        '    except KeyError as exc:\n        raise HTTPException(400, "wrong diagnostic") from exc\n    except ValueError as exc:\n        raise HTTPException(400, "wrong diagnostic") from exc',
        base + "test_preview_rejects_invalid_render_options_before_rendering",
        "",
        3,
    ),
    (
        "missing-master-diagnostic",
        'raise HTTPException(404, f"no local master for {work_id}")',
        'raise HTTPException(404, f"no pixels for {work_id}")',
        base + "test_preview_reports_missing_master_before_attempting_a_render",
        "",
        1,
    ),
    (
        "render-error-diagnostic",
        'raise HTTPException(500, f"render failed: {exc}")',
        'raise HTTPException(500, f"render unavailable: {exc}")',
        base + "test_preview_turns_render_failures_into_a_clear_server_error",
        "",
        1,
    ),
    (
        "missing-master-order",
        "    if master is None:\n",
        "    if master is None:\n        " + call + "\n",
        base + "test_preview_reports_missing_master_before_attempting_a_render",
        "",
        1,
    ),
]
try:
    for name, old, new, node, select, count in cases:
        assert section.count(old) == 1, (name, section.count(old))
        mutated = s[:start] + section.replace(old, new, 1) + s[end:]
        p.write_text(mutated)
        args = [
            str(root / ".venv/bin/python"),
            "-m",
            "pytest",
            node,
            "--no-cov",
            "-q",
            "--tb=short",
            "--junitxml=" + str(out / (name + "-red.xml")),
        ]
        if select:
            args += ["-k", select]
        [f.unlink() for f in (p.parent / "__pycache__").glob("main.*.pyc")]
        red = subprocess.run(args, cwd=root, capture_output=True, text=True)
        (out / (name + "-red.log")).write_text(red.stdout + red.stderr)
        p.write_bytes(original)
        assert p.read_bytes() == original
        args[args.index("--junitxml=" + str(out / (name + "-red.xml")))] = "--junitxml=" + str(
            out / (name + "-green.xml")
        )
        [f.unlink() for f in (p.parent / "__pycache__").glob("main.*.pyc")]
        green = subprocess.run(args, cwd=root, capture_output=True, text=True)
        (out / (name + "-green.log")).write_text(green.stdout + green.stderr)
        row = {
            "name": name,
            "node": node,
            "selection": select,
            "expected_failures": count,
            "red_exit": red.returncode,
            "green_exit": green.returncode,
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "mutation": {"old": old, "new": new},
        }
        rows.append(row)
        (out / "faults.json").write_text(json.dumps(rows, indent=2))
        print(name, red.returncode, green.returncode, flush=True)
        assert red.returncode == 1 and green.returncode == 0, (name, red.stdout[-1200:])
finally:
    p.write_bytes(original)
