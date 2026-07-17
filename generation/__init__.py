"""V1.5 Workstream 2: router + LLM worker + retry pipeline.

Contamination guard: nothing in this package may import from `validator/`
conversation state, and `validator/` must never import from here. The
validator sees only artifacts on disk (generated code + register map JSON).
"""
