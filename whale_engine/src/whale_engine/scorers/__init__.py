"""Whale scorer registry.

Each scorer module exposes `diagnose(snapshot: dict) -> dict` — a pure,
deterministic function of one snapshot. Adding a whale = adding a module here
and listing it in WHALES; fetch/CLI/snapshots are shared and untouched.
"""

from __future__ import annotations

from importlib import import_module

WHALES = ("buffett", "graham")


def get_diagnose(whale: str):
    if whale not in WHALES:
        raise ValueError(f"unknown whale {whale!r} (available: {', '.join(WHALES)})")
    return import_module(f"whale_engine.scorers.{whale}").diagnose
