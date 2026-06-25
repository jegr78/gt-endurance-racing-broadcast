#!/usr/bin/env python3
"""Stdlib unit checks for the read-only Producer-tab parser.
Run: python3 tests/test_producer.py"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
import producer as p


def t_header_mode_parses_three_columns():
    text = ("Part,Producer,MagicDNS\r\n"
            "1,Alice,producer-a.tail1234.ts.net\r\n"
            "2,Bob,producer-b.tail1234.ts.net\r\n")
    assert p.parse_producer_rows(text) == [
        {"part": "1", "producer": "Alice", "magicdns": "producer-a.tail1234.ts.net"},
        {"part": "2", "producer": "Bob", "magicdns": "producer-b.tail1234.ts.net"},
    ]


def t_header_synonyms_and_reordered_columns():
    text = ("MagicDNS,Magic-DNS-IGNORED,Producer,Part\r\n"  # first match wins for magicdns
            "host-x.ts.net,zzz,Carol,3\r\n")
    rows = p.parse_producer_rows(text)
    assert rows == [{"part": "3", "producer": "Carol", "magicdns": "host-x.ts.net"}], rows


def t_magic_dns_spaced_header_synonym():
    text = "Part,Producer,Magic DNS\r\n1,Dan,d.ts.net\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "1", "producer": "Dan", "magicdns": "d.ts.net"}]


def t_duplicates_preserved():
    text = ("Part,Producer,MagicDNS\r\n"
            "2,Bob,producer-b.ts.net\r\n"
            "3,Bob,producer-b.ts.net\r\n")
    rows = p.parse_producer_rows(text)
    assert len(rows) == 2 and rows[0]["producer"] == rows[1]["producer"] == "Bob", rows


def t_empty_magicdns_cell_kept():
    text = "Part,Producer,MagicDNS\r\n4,Eve,\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "4", "producer": "Eve", "magicdns": ""}]


def t_blank_spacer_rows_dropped():
    text = "Part,Producer,MagicDNS\r\n,,\r\n5,Frank,f.ts.net\r\n"
    assert p.parse_producer_rows(text) == [
        {"part": "5", "producer": "Frank", "magicdns": "f.ts.net"}]


def t_missing_header_returns_empty():
    # No recognizable header row -> empty (no positional fallback).
    text = "1,Alice,a.ts.net\r\n2,Bob,b.ts.net\r\n"
    assert p.parse_producer_rows(text) == []


def t_partial_header_returns_empty():
    text = "Part,Producer\r\n1,Alice\r\n"  # MagicDNS column absent
    assert p.parse_producer_rows(text) == []


def t_empty_text_returns_empty():
    assert p.parse_producer_rows("") == []
    assert p.parse_producer_rows(None) == []


def t_resolve_producer_name_exact_fqdn_match():
    rows = p.parse_producer_rows(
        "Part,Producer,MagicDNS\r\n"
        "1,Alice,producer-a.tail1234.ts.net\r\n"
        "2,Bob,producer-b.tail1234.ts.net\r\n")
    assert p.resolve_producer_name(rows, "producer-b.tail1234.ts.net") == "Bob"
    # Case-insensitive + trailing-dot tolerant (mirrors magicdns_is_self).
    assert p.resolve_producer_name(rows, "PRODUCER-A.tail1234.ts.net.") == "Alice"


def t_resolve_producer_name_first_matching_row_wins():
    rows = p.parse_producer_rows(
        "Part,Producer,MagicDNS\r\n"
        "1,Bob,producer-b.ts.net\r\n"
        "2,Bob,producer-b.ts.net\r\n")
    assert p.resolve_producer_name(rows, "producer-b.ts.net") == "Bob"


def t_resolve_producer_name_no_match_returns_empty():
    rows = p.parse_producer_rows("Part,Producer,MagicDNS\r\n1,Alice,producer-a.ts.net\r\n")
    assert p.resolve_producer_name(rows, "producer-z.ts.net") == ""


def t_resolve_producer_name_blank_self_or_rows_returns_empty():
    rows = p.parse_producer_rows("Part,Producer,MagicDNS\r\n1,Alice,producer-a.ts.net\r\n")
    assert p.resolve_producer_name(rows, "") == ""        # own identity unknown
    assert p.resolve_producer_name(rows, None) == ""
    assert p.resolve_producer_name([], "producer-a.ts.net") == ""


def t_resolve_producer_name_skips_empty_magicdns_and_empty_producer():
    rows = [{"part": "1", "producer": "Eve", "magicdns": ""},          # no magicdns -> never self
            {"part": "2", "producer": "", "magicdns": "host.ts.net"}]   # self but no name
    assert p.resolve_producer_name(rows, "") == ""
    assert p.resolve_producer_name(rows, "host.ts.net") == ""           # matched row has no producer


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("t_") and callable(fn):
            fn(); print("ok", name)
    print("all producer tests passed")
