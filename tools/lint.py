#!/usr/bin/env python3
"""Run the ruff linter over the repo (config: ruff.toml at the repo root), plus a
small in-house guard that mirrors CodeQL's py/empty-except (ruff can't — see below).

    python3 tools/lint.py          # check only (what CI runs)
    python3 tools/lint.py --fix    # auto-fix what ruff can (e.g. unused imports)

Ruff is a single external binary, NOT vendored — install once:
  macOS:  brew install ruff      Windows:  winget install astral-sh.ruff
  Linux:  pipx/pip install ruff (or the distro package)
The rule set mirrors the GitHub code-scanning (CodeQL) classes — see ruff.toml.

The empty-except guard exists because ruff's S110 stays OFF (it would re-flag the
documented `except ...: pass  # reason` blocks CodeQL accepts). This guard
reproduces CodeQL's actual behavior — flag an empty handler (`pass`/`...`) with NO
explanatory comment, EXCEPT the benign idioms CodeQL also ignores (a deliberate
`raise` in the try, or an optional-import / KeyboardInterrupt-style handler). So a
missing comment fails the gate locally/pre-push instead of surfacing post-merge.
"""
import ast, io, os, shutil, subprocess, sys, tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Caught types for which a silent `pass` is an accepted idiom (CodeQL does not
# flag these): optional imports and CLI/interpreter-shutdown signals.
_BENIGN_EXC = frozenset({"ImportError", "ModuleNotFoundError", "KeyboardInterrupt",
                         "SystemExit", "StopIteration", "GeneratorExit"})


def _comment_lines(source):
    """1-based line numbers carrying a `#` comment (best-effort)."""
    lines = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # tokenizer gave up; the ast.parse below is the authority anyway
    return lines


def _caught_names(handler):
    """The simple names of the exception types a handler catches (empty = bare)."""
    typ = handler.type
    if typ is None:
        return set()
    items = typ.elts if isinstance(typ, ast.Tuple) else [typ]
    out = set()
    for it in items:
        if isinstance(it, ast.Name):
            out.add(it.id)
        elif isinstance(it, ast.Attribute):
            out.add(it.attr)
    return out


def find_empty_excepts(source):
    """Line numbers of `except` handlers that silently swallow — body is only
    `pass`/`...` with no comment in the handler — EXCLUDING the idioms CodeQL
    py/empty-except also ignores: a deliberate `raise` anywhere in the try body
    (e.g. assert-raises tests) and handlers catching only benign types
    (ImportError/KeyboardInterrupt/...). Returns [] for unparseable source.
    Pure → unit-tested in tests/test_lint.py."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    comments = _comment_lines(source)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        try_raises = any(isinstance(n, ast.Raise)
                         for s in node.body for n in ast.walk(s))
        for h in node.handlers:
            if len(h.body) != 1:
                continue
            stmt = h.body[0]
            empty = isinstance(stmt, ast.Pass) or (
                isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is Ellipsis)
            if not empty:
                continue
            end = getattr(stmt, "end_lineno", stmt.lineno)
            if any(h.lineno <= c <= end for c in comments):
                continue                       # has an explanatory comment
            if try_raises:
                continue                       # deliberate raise in try (assert-raises idiom)
            names = _caught_names(h)
            if names and names <= _BENIGN_EXC:
                continue                       # optional-import / Ctrl-C style handler
            hits.append(h.lineno)
    return hits


def _python_files(root):
    """Tracked .py files (git, so dist/runtime/incoming stay excluded); a plain
    walk is the fallback when git is unavailable."""
    try:
        out = subprocess.check_output(["git", "-C", root, "ls-files", "*.py"],
                                      text=True)
        return [os.path.join(root, p) for p in out.split() if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        skip = {"dist", "runtime", "incoming", ".git", "__pycache__", ".venv"}
        files = []
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            files += [os.path.join(dirpath, n) for n in names if n.endswith(".py")]
        return files


def check_empty_excepts(root):
    """(relpath, lineno) for every uncommented silent-swallow except in the repo."""
    bad = []
    for path in _python_files(root):
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for ln in find_empty_excepts(src):
            bad.append((os.path.relpath(path, root), ln))
    return sorted(bad)


def main():
    if not shutil.which("ruff"):
        sys.exit("lint: ruff not found on PATH.\n"
                 "  install: brew install ruff  (macOS) | winget install astral-sh.ruff"
                 "  (Windows) | pipx install ruff  (Linux)")
    rc = subprocess.call(["ruff", "check", ROOT] + sys.argv[1:])
    bad = check_empty_excepts(ROOT)
    if bad:
        print("\nempty-except (CodeQL py/empty-except) — add a short reason in the "
              "handler body, e.g. `pass  # already gone`:")
        for relpath, lineno in bad:
            print(f"  {relpath}:{lineno}: except body is only pass/... with no comment")
        rc = rc or 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
