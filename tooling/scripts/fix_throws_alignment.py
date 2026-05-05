#!/usr/bin/env python3
"""
Reformat method/constructor `throws` clauses to match the spec:

- `throws` always on its own line, single-indented (4 spaces past
  the method declaration).
- Exception types stay on the same line as `throws` if the assembled
  line fits within 80 chars.
- When wrapping is required, continuation lines column-align with
  the first exception type (i.e., paren-aligned to `throws ` width).

JDT alone cannot produce the column-aligned wrap shape — its
`alignment_for_throws_clause_in_method_declaration` settings can put
`throws` on its own line and pack-as-many-as-fit, but continuations
land at the default `throws` indent rather than under the first
exception. This post-JDT pass fixes both cases.
"""

import re
import sys
from pathlib import Path

MAX_LINE = 80

# Match a line whose first non-whitespace token is `throws`.
RE_THROWS_LINE = re.compile(r'^(\s+)throws\s+(.+?)\s*$')

# Validate an exception-type token (after stripping leading
# annotations). Permissive: simple identifier, qualified name, or
# type parameter. Rejects anything containing spaces, parens,
# braces, etc., to avoid accidentally rewriting non-throws code.
RE_EXCEPTION_TYPE = re.compile(r'^[A-Za-z_$][A-Za-z0-9_$.]*$')

# Strip leading annotations from a single token (e.g.
# `@NonNull IOException` -> `IOException`). Tolerates one or more
# annotations with optional `(...)` argument lists.
RE_LEADING_ANNOTATION = re.compile(r'^(?:@\w+(?:\([^)]*\))?\s+)+')


def _strip_annotations(token):
    return RE_LEADING_ANNOTATION.sub('', token).strip()


def _split_top_level_commas(text):
    """Split `text` at commas that sit at paren-depth zero.

    Annotation arguments may contain commas inside `(...)` (e.g.
    `@MyAnno(a=1, b=2) Foo`); those commas must not split the
    enclosing exception list. Returns a list of stripped, non-empty
    tokens.
    """
    tokens = []
    current = []
    depth = 0
    for ch in text:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == ',' and depth == 0:
            piece = ''.join(current).strip()
            if piece:
                tokens.append(piece)
            current = []
        else:
            current.append(ch)
    piece = ''.join(current).strip()
    if piece:
        tokens.append(piece)
    return tokens


def _collect_clause(lines, start_idx):
    """Starting at `lines[start_idx]` which matches a `throws` line,
    collect the full clause across continuation lines.

    Returns `(indent, types, suffix, consumed)` on success:

    - `indent`: leading whitespace of the `throws` line.
    - `types`: list of exception-type tokens (with original
      annotation prefixes preserved).
    - `suffix`: trailing `;` if the clause ended with one (interface
      method), else empty string.
    - `consumed`: number of original lines this clause occupies
      (1 for single-line, 2+ for multi-line).

    Returns `None` if parsing fails (the block is left untouched).
    """
    line0 = lines[start_idx].rstrip('\n').rstrip('\r')
    m = RE_THROWS_LINE.match(line0)
    if not m:
        return None

    indent = m.group(1)
    body = m.group(2).strip()

    # Reject if the body contains brace punctuation, which means this
    # isn't a clean `throws ...` line (e.g., `{` from an inline method
    # body). Parens are OK — they appear in annotation arguments like
    # `@MyAnno(value=1)` and are handled by the paren-aware splitter
    # below.
    if any(c in body for c in '{}'):
        return None

    types_text = body
    consumed = 1

    # Walk continuation lines while the current segment ends with a
    # comma (each continuation contributes more types and may end
    # with another comma or with the terminator).
    while types_text.rstrip().endswith(','):
        idx = start_idx + consumed
        if idx >= len(lines):
            return None
        next_line = lines[idx].rstrip('\n').rstrip('\r')
        cont = re.match(r'^(\s+)(.+?)\s*$', next_line)
        if not cont:
            return None
        # Continuation must be indented at least as far as the
        # `throws` line; a de-indented line is structurally
        # something else (next statement, closing brace).
        if len(cont.group(1)) < len(indent):
            return None
        cont_text = cont.group(2).strip()
        # Defense: a whitespace-only continuation line (.+? matched
        # whitespace, .strip() emptied it) means there's nothing to
        # contribute — punt to avoid scanning to EOF on a stray blank.
        if not cont_text:
            return None
        if any(c in cont_text for c in '{}'):
            return None
        types_text = types_text + ' ' + cont_text
        consumed += 1

    # Detect and strip the optional trailing `;`.
    suffix = ''
    if types_text.endswith(';'):
        suffix = ';'
        types_text = types_text[:-1].rstrip()

    # Defensive — strip a stray trailing comma if we somehow got one.
    types_text = types_text.rstrip(',').strip()

    # Split on commas at paren-depth 0. Annotation arguments may
    # contain commas inside `(...)` (e.g., `@MyAnno(a=1, b=2) Foo`)
    # and must not be split.
    raw_types = _split_top_level_commas(types_text)
    if not raw_types:
        return None

    # Validate each token. After stripping leading annotations the
    # remainder must be a plain identifier (possibly qualified).
    for t in raw_types:
        if not RE_EXCEPTION_TYPE.match(_strip_annotations(t)):
            return None

    return indent, raw_types, suffix, consumed


def _emit_clause(indent, types, suffix):
    """Render the clause in spec layout. Returns the full text of
    the new clause including a trailing newline.

    If the assembled single-line form fits within `MAX_LINE`, emit
    on one line. Otherwise emit with each exception on its own line,
    continuations column-aligned with the first exception type.
    """
    single_line = f"{indent}throws {', '.join(types)}{suffix}"
    if len(single_line) <= MAX_LINE:
        return single_line + '\n'

    # A single exception cannot be wrapped — its name is atomic, so the
    # column-aligned-wrap branch below would just re-emit the same long
    # line. Return single-line form unconditionally; the over-budget
    # length is a structural fact about the identifier, not something
    # this script can fix.
    if len(types) == 1:
        return single_line + '\n'

    cont_indent = ' ' * (len(indent) + len('throws '))
    parts = [f"{indent}throws {types[0]}"]
    for t in types[1:]:
        parts[-1] = parts[-1] + ','
        parts.append(f"{cont_indent}{t}")
    parts[-1] = parts[-1] + suffix
    return '\n'.join(parts) + '\n'


def process_file(filepath):
    """Rewrite `throws` clauses in `filepath` to spec layout. Returns
    `(changed, fixes)` — `changed` is True iff at least one clause
    was rewritten; `fixes` is the count of rewritten clauses."""
    path = Path(filepath)
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)

    new_lines = []
    fixes = 0
    i = 0

    while i < len(lines):
        result = _collect_clause(lines, i)
        if result is None:
            new_lines.append(lines[i])
            i += 1
            continue

        indent, types, suffix, consumed = result
        original = ''.join(lines[i:i + consumed])
        new_block = _emit_clause(indent, types, suffix)

        new_lines.append(new_block)
        if new_block != original:
            fixes += 1
        i += consumed

    if fixes > 0:
        path.write_text(''.join(new_lines), encoding='utf-8')
    return fixes > 0, fixes


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_throws_alignment",
        description=(
            "Reformat method/constructor throws clauses to spec "
            "layout: throws on its own line, exceptions packed when "
            "they fit, column-aligned wrap when they don't."
        ),
    )

    total = 0
    modified = 0
    total_fixes = 0
    for java_file in iter_target_files(args):
        total += 1
        changed, fixes = process_file(java_file)
        if changed:
            modified += 1
            total_fixes += fixes
            print(f"  Fixed {fixes:3d} in: {java_file}")

    print(
        f"\nProcessed {total} files, modified {modified}, "
        f"{total_fixes} throws-clause fixes applied."
    )


if __name__ == '__main__':
    main()
