
import subprocess
import sys


def test_design_coverage_script_passes():
    result = subprocess.run([sys.executable, "tools/verify_design_coverage.py"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
