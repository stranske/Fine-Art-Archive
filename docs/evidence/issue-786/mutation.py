"""Replay the fit-cache regression against a surgical production hash bypass.

Run from a clean disposable checkout using its pytest-enabled Python.
Always restores the exact source bytes before returning.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

source = Path('src/fine_art_archive/eink/feed.py')
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
original = source.read_bytes()
needle = b'{mtime}|{effective_fit}'
assert original.count(needle) == 1
command = [sys.executable, '-m', 'pytest', 'tests/test_eink_feed_endpoints.py', '-k', 'fit', '-q', '-o', 'addopts=']
receipt = {'source_sha256': hashlib.sha256(original).hexdigest(), 'mutation': 'Remove only |{effective_fit} from item_etag hashed representation', 'command': command[1:]}
try:
    source.write_bytes(original.replace(needle, b'{mtime}'))
    red = subprocess.run(command + ['--junitxml=' + str(output / 'mutation-red.xml')], capture_output=True, text=True)
    (output / 'mutation-red.log').write_text(red.stdout + red.stderr)
    receipt['red_exit'] = red.returncode
finally:
    source.write_bytes(original)
    receipt['restored_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
assert receipt['source_sha256'] == receipt['restored_sha256']
green = subprocess.run(command + ['--junitxml=' + str(output / 'restored-green.xml')], capture_output=True, text=True)
(output / 'restored-green.log').write_text(green.stdout + green.stderr)
receipt['green_exit'] = green.returncode
(output / 'mutation-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
assert receipt['red_exit'] == 1 and receipt['green_exit'] == 0, receipt
print(json.dumps(receipt))
