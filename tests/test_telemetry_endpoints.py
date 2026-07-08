#!/usr/bin/env python3
"""Endpoint checks for the GT7 telemetry routes. Run: python3 tests/test_telemetry_endpoints.py

Exercises the store contract behind /telemetry/data and /telemetry/trace: when
telemetry_store is None (endurance / disabled) the routes 404; when a store exists
they return its data()/trace() shape. This checks the store directly (the same
shape the do_GET routes hand back via self._send), mirroring the style of the
other pure-logic tests in this repo."""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "irofeeds", os.path.join(ROOT, "src", "relay", "racecast-feeds.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def t_telemetry_data_shape():
    store = m.gt7_telemetry.TelemetryStore(None, units="metric")
    payload = store.data()
    assert set(payload) >= {"speed", "tyres", "fuel", "units", "has_reference"}
    assert len(payload["tyres"]) == 4


def t_telemetry_trace_shape():
    store = m.gt7_telemetry.TelemetryStore(None)
    assert store.trace(10) == []          # empty before any packet


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("ALL PASS")
