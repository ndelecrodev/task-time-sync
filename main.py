"""Entrypoint for the SOP pipeline.

Run with ``python main.py`` after installing the project (``pip install -e .``).
"""

from src.sop_pipeline.pipeline import run

if __name__ == "__main__":
    run()
