"""
Runs each test module in its own Python process and reports which ones failed.

test_package imports the whole mod as the game would, so it needs a process where nothing has imported the mod yet.
"""

import glob
import os
import subprocess
import sys

if sys.version_info[:2] != (3, 7):
    sys.exit('Run the tests with Python 3.7: they execute the game\'s own Python 3.7 bytecode.')

here = os.path.dirname(os.path.abspath(__file__))
failed = []
for path in sorted(glob.glob(os.path.join(here, 'tests', 'test_*.py'))):
    print('==', os.path.basename(path), flush=True)
    if subprocess.run([sys.executable, path]).returncode:
        failed.append(os.path.basename(path))
print('\nFailed: ' + ', '.join(failed) if failed else '\nAll test modules passed.')
sys.exit(1 if failed else 0)
