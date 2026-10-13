import hashlib
import json
import os
import pathlib
import subprocess
import sys

root = pathlib.Path.cwd()
out = pathlib.Path(sys.argv[1])
receipt = []
cases = [
    (
        "fit",
        "src/fine_art_archive/eink/feed.py",
        "|{effective_fit}",
        "",
        ["tests/test_eink_feed_endpoints.py", "-k", "fit"],
    ),
    (
        "strategy-etag",
        "src/fine_art_archive/eink/feed.py",
        "|a11-v1|{render_strategy}",
        "|a11-v1",
        [
            "tests/test_eink_feed_endpoints.py",
            "tests/test_eink_monochrome_delivery.py",
            "-k",
            "invalidates_etag or invalidates_cached_strategy",
        ],
    ),
    (
        "strategy-pixels",
        "src/fine_art_archive/eink/targets.py",
        '    if strategy not in {"color", "grayscale", "duotone"}:',
        '    strategy = "color"\n    if strategy not in {"color", "grayscale", "duotone"}:',
        [
            "tests/test_eink_monochrome_delivery.py",
            "-k",
            "test_companion_feed_and_sd_apply_reported_strategy",
        ],
    ),
]
for name, path, needle, replacement, args in cases:
    source = root / path
    original = source.read_bytes()
    assert original.count(needle.encode()) == 1
    command = [sys.executable, "-m", "pytest", *args, "-q", "-o", "addopts="]
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    try:
        source.write_bytes(original.replace(needle.encode(), replacement.encode()))
        red = subprocess.run(command, capture_output=True, text=True, env=env)
        (out / (name + "-red.log")).write_text(red.stdout + red.stderr)
    finally:
        source.write_bytes(original)
    assert source.read_bytes() == original
    green = subprocess.run(command, capture_output=True, text=True, env=env)
    (out / (name + "-green.log")).write_text(green.stdout + green.stderr)
    entry = {
        "name": name,
        "source": path,
        "sha256": hashlib.sha256(original).hexdigest(),
        "red_exit": red.returncode,
        "green_exit": green.returncode,
        "red_summary": red.stdout.splitlines()[-1:],
        "green_summary": green.stdout.splitlines()[-1:],
    }
    receipt.append(entry)
    print(json.dumps(entry), flush=True)
    assert red.returncode == 1 and green.returncode == 0
(out / "789-mutation-receipt.json").write_text(json.dumps(receipt, indent=2))
