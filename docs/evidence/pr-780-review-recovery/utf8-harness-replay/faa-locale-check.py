import json
import pathlib
import runpy
import sys

P = pathlib.Path(__file__).parent
original_write = pathlib.Path.write_text
original_read = pathlib.Path.read_text
seen = []


def write(self, text, *args, **kwargs):
    encoding = kwargs.get("encoding", args[0] if args else None)
    seen.append(["write", str(self), encoding])
    assert encoding == "utf-8", (self, encoding)
    return original_write(self, text, *args, **kwargs)


def read(self, *args, **kwargs):
    encoding = kwargs.get("encoding", args[0] if args else None)
    seen.append(["read", str(self), encoding])
    assert encoding == "utf-8", (self, encoding)
    return original_read(self, *args, **kwargs)


pathlib.Path.write_text = write
pathlib.Path.read_text = read
try:
    sys.argv = [
        "docs/evidence/pr-780-review-recovery/mutation-harness.txt",
        str(P / "faa-locale-replay"),
    ]
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    pathlib.Path.write_text = original_write
    pathlib.Path.read_text = original_read
(P / "faa-locale-proof.json").write_text(
    json.dumps(
        {
            "control": "Every harness text read/write rejects an unspecified or non-UTF8 encoding; child tests use real path-scoped ASCII-default I/O.",
            "text_operations": seen,
            "implicit_default_operations": 0,
        },
        indent=2,
    ),
    encoding="utf-8",
)
