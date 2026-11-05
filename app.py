"""Convenient entry point: python app.py. This is a FastAPI web app."""
from pathlib import Path
import runpy
if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parent / 'scripts/run-local.py'),run_name='__main__')
