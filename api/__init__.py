"""V1.5 WS3: thin FastAPI service exposing the Python pipeline to the UI.

This layer orchestrates and streams; it never reimplements pipeline logic.
The contamination guard is untouched — generation runs in-process, the
validator stays a subprocess invoked by generation/pipeline.py.
"""
