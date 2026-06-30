#!/usr/bin/env python3
"""Unit checks for the Event Notes Sheet-tab parser (pure, stdlib only)."""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_path = os.path.join(HERE, "..", "src", "scripts", "event_notes.py")
_spec = importlib.util.spec_from_file_location("event_notes", _path)
event_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(event_notes)
parse = event_notes.parse_event_notes


def t_basic_rows():
    csv_text = "Heading,Note,Priority\nWelcome,Mind the sponsor read,Important\n,Running order on screen,\n"
    out = parse(csv_text)
    assert out == [
        {"heading": "Welcome", "note": "Mind the sponsor read", "priority": "important"},
        {"heading": "", "note": "Running order on screen", "priority": "info"},
    ], out


def t_header_order_independent():
    csv_text = "Note,Priority,Heading\nDo the thing,info,Hi\n"
    out = parse(csv_text)
    assert out == [{"heading": "Hi", "note": "Do the thing", "priority": "info"}], out


def t_priority_normalisation():
    csv_text = "Heading,Note,Priority\nA,n1,IMPORTANT\nB,n2,important\nC,n3,Info\nD,n4,\nE,n5,banana\n"
    pris = [r["priority"] for r in parse(csv_text)]
    assert pris == ["important", "important", "info", "info", "info"], pris


def t_empty_note_rows_skipped():
    csv_text = "Heading,Note,Priority\nH,,Important\nH2,real note,\n"
    out = parse(csv_text)
    assert [r["note"] for r in out] == ["real note"], out


def t_missing_columns_and_empty_degrade():
    assert parse("") == []
    assert parse("Heading,Priority\nH,Important\n") == []        # no Note column
    assert parse("Heading,Note,Priority\n") == []                 # header only
    # Missing Heading/Priority columns still parse Note rows:
    out = parse("Note\njust a note\n")
    assert out == [{"heading": "", "note": "just a note", "priority": "info"}], out


def run():
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")


if __name__ == "__main__":
    run()
