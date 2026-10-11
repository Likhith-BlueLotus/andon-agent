"""Deterministic signal analytics behind the read-only agent tools (``agents/tools.py``).

Pure functions on numpy arrays: no store access, no LLM, no ground truth. Every function here is
deterministic for the same input, which is what lets the Verifier re-run a tool and compare.
"""
