#!/usr/bin/env python3
"""Unit checks for the empty-except guard in tools/lint.py (mirrors CodeQL's
py/empty-except locally so a missing comment fails the gate pre-push, not
post-merge). Run: python3 tests/test_lint.py"""
import importlib.util, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("lintmod", os.path.join(ROOT, "tools", "lint.py"))
lint = importlib.util.module_from_spec(spec); spec.loader.exec_module(lint)

# Fixtures are SOURCE STRINGS (not live code) so this test file itself stays clean.
SWALLOW = "try:\n    f()\nexcept OSError:\n    pass\n"
SWALLOW_ELLIPSIS = "try:\n    f()\nexcept OSError:\n    ...\n"
COMMENT_INLINE = "try:\n    f()\nexcept OSError:\n    pass  # already gone\n"
COMMENT_LINE = "try:\n    f()\nexcept OSError:\n    # already gone\n    pass\n"
NON_EMPTY = "try:\n    f()\nexcept OSError:\n    log()\n"
RAISE_IN_TRY = "try:\n    f()\n    raise AssertionError\nexcept ValueError:\n    pass\n"
BENIGN_IMPORT = "try:\n    import x\nexcept ImportError:\n    pass\n"
BENIGN_KBD = "try:\n    loop()\nexcept KeyboardInterrupt:\n    pass\n"
BARE_EXCEPT = "try:\n    f()\nexcept:\n    pass\n"
MIXED_BENIGN = "try:\n    f()\nexcept (ImportError, OSError):\n    pass\n"
DOTTED = "try:\n    f()\nexcept asyncio.TimeoutError:\n    pass\n"


def t_flags_uncommented_swallow():
    assert lint.find_empty_excepts(SWALLOW) == [3]          # the `except` line


def t_flags_uncommented_ellipsis_body():
    assert lint.find_empty_excepts(SWALLOW_ELLIPSIS) == [3]


def t_inline_comment_suppresses():
    assert lint.find_empty_excepts(COMMENT_INLINE) == []


def t_comment_line_in_body_suppresses():
    assert lint.find_empty_excepts(COMMENT_LINE) == []


def t_non_empty_handler_not_flagged():
    assert lint.find_empty_excepts(NON_EMPTY) == []


def t_raise_in_try_is_excluded():
    # assert-raises test idiom — CodeQL ignores it, so must we.
    assert lint.find_empty_excepts(RAISE_IN_TRY) == []


def t_benign_caught_types_excluded():
    assert lint.find_empty_excepts(BENIGN_IMPORT) == []      # optional-import guard
    assert lint.find_empty_excepts(BENIGN_KBD) == []         # Ctrl-C swallow


def t_bare_except_is_flagged():
    assert lint.find_empty_excepts(BARE_EXCEPT) == [3]


def t_mixed_benign_and_real_is_flagged():
    # catches a real error type alongside a benign one -> still a silent swallow
    assert lint.find_empty_excepts(MIXED_BENIGN) == [3]


def t_dotted_exception_name_uses_attr():
    assert lint.find_empty_excepts(DOTTED) == [3]            # asyncio.TimeoutError, no comment


def t_syntax_error_source_is_safe():
    assert lint.find_empty_excepts("def (:\n  pass\n") == []


def t_repo_is_clean():
    # The whole repo must already satisfy the guard (this is the regression that
    # would have caught the 5 alerts from #139/#142 before they reached CodeQL).
    assert lint.check_empty_excepts(ROOT) == [], lint.check_empty_excepts(ROOT)


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("t_") and callable(fn):
            fn(); print("ok", n)
    print("ALL PASS")
