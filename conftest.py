"""
pytest configuration — makes the WilloWisp modules importable from tests/
without installing the package. Placing this at the project root causes pytest
to prepend this directory to sys.path, so `import iscs_reports` etc. resolve.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
