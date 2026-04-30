#!/usr/bin/env python3
"""
Fix NeedBraces violations and over-eager single-line if statements.

Single-line / brace-less `if` form is RESERVED for short-circuit
control-flow: the body must be `return`, `continue`, `break`, or
`throw`. Assignments, method calls, and other statements always get
braces, even when the result would fit on one line.

For a standalone `if` (no else) with body `body;` on the next line:

    if (cond)
        body;

If `body;` is short-circuit AND the collapsed line fits within 80
chars, prefer Tier 1 (single line):

    if (cond) body;          # only when body is return/continue/break/throw

Otherwise add braces (Tier 2):

    if (cond) {
        body;
    }

When an `else` clause is present, ALWAYS use braces on both branches —
single-line form is never used for if/else pairs.

This script also reformats existing one-liners
`if (cond) someVar = …;` (or any non-short-circuit body) by adding
braces — those are valid checkstyle but violate the project's
coding-standards rule.

Targets violations checkstyle's NeedBraces module flags AND the
project-specific over-eager-inline-if convention. Leaves correctly
formatted code alone.
"""

import re
import sys
from pathlib import Path

MAX_LINE = 80

# Match an if/else if/else line that opens a body on the next line
# (no trailing brace, no trailing semicolon).
RE_IF_OPEN = re.compile(
    r'^(?P<indent>[ \t]*)(?P<kw>if|else\s+if)\s*\((?P<cond>.*)\)\s*$'
)
RE_ELSE_OPEN = re.compile(
    r'^(?P<indent>[ \t]*)else\s*$'
)
# Leading whitespace on a line (always matches — used for indent
# extraction).
RE_LEADING_WS = re.compile(r'^([ \t]*)')
# Body line: deeper indent, ends with ';' (single statement)
RE_BODY_STMT = re.compile(
    r'^(?P<indent>[ \t]+)(?P<stmt>[^\s].*;)\s*$'
)
# Match an inline `if (cond) body;` on a single line.
RE_IF_INLINE = re.compile(
    r'^(?P<indent>[ \t]*)if\s*\((?P<cond>.+)\)\s+(?P<body>\S.*;)\s*$'
)


def line_indent(line):
    return line[:len(line) - len(line.lstrip(' \t'))]


SHORT_CIRCUIT_KEYWORDS = ('return', 'continue', 'break', 'throw')


def is_short_circuit_stmt(stmt):
    """Return True if stmt is a short-circuit control-flow statement
    (return/continue/break/throw). Single-line / brace-less form is
    only allowed for these.
    """
    s = stmt.strip()
    for kw in SHORT_CIRCUIT_KEYWORDS:
        if s == f'{kw};':
            return True
        if s.startswith(f'{kw} ') or s.startswith(f'{kw}('):
            return True
    return False


def can_inline(parent_indent, prefix, body_stmt):
    """Return collapsed line if it fits within MAX_LINE AND the body is
    a short-circuit statement. Otherwise return None (caller should add
    braces). Single-line / brace-less form is reserved for short-circuit
    flow only — assignments and method calls always get braces.
    """
    if not is_short_circuit_stmt(body_stmt):
        return None
    candidate = f"{parent_indent}{prefix} {body_stmt}"
    if len(candidate) <= MAX_LINE:
        return candidate
    return None


def collapse_or_brace_block(lines, header_idx, body_idx, parent_indent,
                            header_prefix):
    """Try to inline header+body. Returns (new_lines, lines_consumed).

    new_lines: list of replacement lines (with trailing newline).
    lines_consumed: how many original lines this consumed (>= 2).
    Any blank or comment lines between header_idx and body_idx are
    preserved in the output.
    """
    body_line = lines[body_idx]
    body_match = RE_BODY_STMT.match(body_line.rstrip('\n').rstrip('\r'))
    if not body_match:
        return None, 0

    stmt = body_match.group('stmt').strip()
    body_indent = body_match.group('indent')
    if len(body_indent) <= len(parent_indent):
        return None, 0

    # Preserve any blank/comment lines between the header and the body
    # so they aren't silently dropped when we rewrite the block.
    interleaved = lines[header_idx + 1:body_idx]

    inlined = can_inline(parent_indent, header_prefix, stmt)
    consumed = body_idx - header_idx + 1

    if inlined is not None and not interleaved:
        return [inlined + '\n'], consumed

    if inlined is not None:
        # Inline form would lose interleaved comments. Fall through to
        # braced form which can preserve them inside the block.
        pass

    braced = [f"{parent_indent}{header_prefix} {{\n"]
    braced.extend(interleaved)
    braced.append(f"{body_indent}{stmt}\n")
    braced.append(f"{parent_indent}}}\n")
    return braced, consumed


def find_next_code_line(lines, start_idx):
    """Return index of the next non-blank, non-comment line, or len."""
    n = len(lines)
    i = start_idx
    in_block = False
    while i < n:
        s = lines[i].strip()
        if in_block:
            if '*/' in s:
                in_block = False
            i += 1
            continue
        if not s:
            i += 1
            continue
        if s.startswith('//'):
            i += 1
            continue
        if s.startswith('/*'):
            if '*/' not in s:
                in_block = True
            i += 1
            continue
        return i
    return n


# The project's coding standards mandate 4-space indentation for all
# Java source. Hard-coded here rather than detected per-file, because
# any reliable detection requires scanning multiple nesting levels and
# this script only ever rewrites Java files in this repo.
INDENT_UNIT = '    '


def process_file(path):
    """Rewrite file in place if any short-circuit if/else can be fixed.

    Returns (changed, fixes_applied).
    """
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines(True)
    n = len(lines)

    out = []
    i = 0
    fixes = 0

    in_block_comment = False

    while i < n:
        raw = lines[i]
        stripped_no_nl = raw.rstrip('\n').rstrip('\r')
        s = stripped_no_nl.strip()

        if in_block_comment:
            out.append(raw)
            if '*/' in s:
                in_block_comment = False
            i += 1
            continue
        if s.startswith('/*') and '*/' not in s:
            in_block_comment = True
            out.append(raw)
            i += 1
            continue
        if s.startswith('//') or s.startswith('*'):
            out.append(raw)
            i += 1
            continue

        # First-pass: catch already-inline `if (cond) body;` where body
        # is NOT a short-circuit control-flow statement. Brace it.
        # If a paired `else` follows on the next non-blank line at the
        # same indent, brace BOTH branches per the if/else-always-
        # braced rule.
        m_inline = RE_IF_INLINE.match(stripped_no_nl)
        if m_inline and not s.startswith('}'):
            inline_cond = m_inline.group('cond')
            # Skip if condition has unbalanced parens (defensive).
            if inline_cond.count('(') == inline_cond.count(')'):
                inline_body = m_inline.group('body').strip()
                if not is_short_circuit_stmt(inline_body):
                    inline_indent = m_inline.group('indent')
                    body_indent = inline_indent + INDENT_UNIT

                    # Look ahead for a paired `else` on the next line
                    # at the same indent. Only collapse the pair when
                    # NO blank/comment lines sit between them — if any
                    # do, we'd have to drop them to produce a single
                    # if/else block, which is destructive. Instead,
                    # fall through and brace only the if branch (the
                    # interleaved lines and the `else` are emitted
                    # untouched in subsequent iterations).
                    else_handled = False
                    next_idx_immediate = i + 1
                    if next_idx_immediate < n:
                        next_line = lines[
                            next_idx_immediate].rstrip(
                                '\n').rstrip('\r')
                        next_stripped = next_line.strip()
                        next_indent = RE_LEADING_WS.match(
                            next_line).group(1)
                        if (next_indent == inline_indent
                                and (next_stripped.startswith('else ')
                                     or next_stripped == 'else'
                                     or next_stripped.startswith(
                                         'else{'))):
                            else_body = next_stripped[4:].strip()
                            # Strip leading '{' if present (else { ...).
                            if else_body.startswith('{'):
                                else_body = else_body[1:].strip()
                            # Detect `else if (cond) stmt;` so we can
                            # emit a properly braced `} else if (...)`
                            # rather than a plain `} else {` wrapping
                            # an unbraced inner if (which would
                            # otherwise need a second pass to clean
                            # up).
                            m_elseif = RE_IF_INLINE.match(else_body)
                            elseif_balanced = (
                                m_elseif is not None
                                and (m_elseif.group('cond').count('(')
                                     == m_elseif.group(
                                         'cond').count(')')))
                            if elseif_balanced:
                                inner_cond = m_elseif.group('cond')
                                inner_body = m_elseif.group(
                                    'body').strip()
                                out.append(
                                    f"{inline_indent}if "
                                    f"({inline_cond}) {{\n")
                                out.append(
                                    f"{body_indent}{inline_body}\n")
                                out.append(
                                    f"{inline_indent}}} else if "
                                    f"({inner_cond}) {{\n")
                                out.append(
                                    f"{body_indent}{inner_body}\n")
                                out.append(f"{inline_indent}}}\n")
                                fixes += 1
                                i = next_idx_immediate + 1
                                else_handled = True
                            # Plain `else stmt;`: single-line else.
                            elif (else_body.endswith(';')
                                    and '{' not in else_body
                                    and '}' not in else_body):
                                # Emit if-else with both braced.
                                out.append(
                                    f"{inline_indent}if "
                                    f"({inline_cond}) {{\n")
                                out.append(
                                    f"{body_indent}{inline_body}\n")
                                out.append(
                                    f"{inline_indent}}} else {{\n")
                                out.append(
                                    f"{body_indent}{else_body}\n")
                                out.append(f"{inline_indent}}}\n")
                                fixes += 1
                                i = next_idx_immediate + 1
                                else_handled = True

                    if not else_handled:
                        out.append(
                            f"{inline_indent}if ({inline_cond}) {{\n")
                        out.append(f"{body_indent}{inline_body}\n")
                        out.append(f"{inline_indent}}}\n")
                        fixes += 1
                        i += 1
                    continue

        m_if = RE_IF_OPEN.match(stripped_no_nl)
        if not m_if:
            out.append(raw)
            i += 1
            continue

        parent_indent = m_if.group('indent')
        kw = m_if.group('kw')
        cond = m_if.group('cond')
        if_header = f"{kw} ({cond})"

        body_idx = find_next_code_line(lines, i + 1)
        if body_idx >= n:
            out.append(raw)
            i += 1
            continue

        # Bail if the body line itself is an `if`, `{`, or other
        # complex construct — only handle plain single-statement bodies.
        body_stripped = lines[body_idx].rstrip('\n').rstrip('\r')
        body_s = body_stripped.strip()
        if (body_s.startswith('{')
                or body_s.endswith('{')
                or not body_s.endswith(';')
                or body_s.startswith('if ')
                or body_s.startswith('if(')):
            out.append(raw)
            i += 1
            continue

        if_replacement, if_consumed = collapse_or_brace_block(
            lines, i, body_idx, parent_indent, if_header)
        if if_replacement is None:
            out.append(raw)
            i += 1
            continue

        # Look for paired else / else if right after the body
        next_idx = i + if_consumed
        else_replacement = None
        else_consumed = 0

        if next_idx < n:
            else_raw = lines[next_idx].rstrip('\n').rstrip('\r')
            m_else_if = RE_IF_OPEN.match(else_raw)
            m_else = RE_ELSE_OPEN.match(else_raw)
            if m_else_if and m_else_if.group('kw') == 'else if':
                if m_else_if.group('indent') == parent_indent:
                    # Recurse-style: collapse the else-if header/body
                    e_body_idx = find_next_code_line(
                        lines, next_idx + 1)
                    if e_body_idx < n:
                        e_body_s = lines[e_body_idx].strip()
                        if (e_body_s.endswith(';')
                                and not e_body_s.startswith('{')
                                and not e_body_s.endswith('{')
                                and not e_body_s.startswith('if ')
                                and not e_body_s.startswith('if(')):
                            e_header = (f"else if "
                                        f"({m_else_if.group('cond')})")
                            new_replacement, new_consumed = (
                                collapse_or_brace_block(
                                    lines, next_idx, e_body_idx,
                                    parent_indent, e_header))
                            if new_replacement is not None:
                                else_replacement = new_replacement
                                else_consumed = new_consumed
            elif m_else and m_else.group('indent') == parent_indent:
                e_body_idx = find_next_code_line(lines, next_idx + 1)
                if e_body_idx < n:
                    e_body_s = lines[e_body_idx].strip()
                    if (e_body_s.endswith(';')
                            and not e_body_s.startswith('{')
                            and not e_body_s.endswith('{')
                            and not e_body_s.startswith('if ')
                            and not e_body_s.startswith('if(')):
                        new_replacement, new_consumed = (
                            collapse_or_brace_block(
                                lines, next_idx, e_body_idx,
                                parent_indent, 'else'))
                        if new_replacement is not None:
                            else_replacement = new_replacement
                            else_consumed = new_consumed

        # If we matched an if/else pair: always brace both branches.
        # Single-line (no-brace) form is only allowed for a standalone
        # `if` — never when an `else` is present.
        if else_replacement is not None:
            if_body_idx = body_idx
            e_first_idx = next_idx + 1
            e_body_idx = find_next_code_line(lines, e_first_idx)
            if_body_indent = line_indent(lines[if_body_idx])
            if_body_stmt = lines[if_body_idx].strip()
            e_body_indent = line_indent(lines[e_body_idx])
            e_body_stmt = lines[e_body_idx].strip()
            if m_else_if and m_else_if.group('kw') == 'else if':
                e_header = f"else if ({m_else_if.group('cond')})"
            else:
                e_header = 'else'
            # Preserve any blank/comment lines between the if header
            # and its body, and between the else header and its body,
            # so the combined rebuild doesn't silently drop them.
            if_interleaved = lines[i + 1:body_idx]
            e_interleaved = lines[next_idx + 1:e_body_idx]
            if_replacement = (
                [f"{parent_indent}{if_header} {{\n"]
                + list(if_interleaved)
                + [f"{if_body_indent}{if_body_stmt}\n"]
                + [f"{parent_indent}}} {e_header} {{\n"]
                + list(e_interleaved)
                + [f"{e_body_indent}{e_body_stmt}\n"]
                + [f"{parent_indent}}}\n"]
            )
            # Combined replacement; clear else_replacement so we
            # don't double-emit.
            out.extend(if_replacement)
            fixes += 2
            i = next_idx + else_consumed
            continue

        # Note: when an else/else-if branch is paired with this if,
        # the earlier `continue` (after writing the combined replacement)
        # exits this iteration, so we only reach this point for a
        # standalone if (else_replacement is None).
        out.extend(if_replacement)
        fixes += 1
        i += if_consumed

    if fixes > 0:
        path.write_text(''.join(out), encoding='utf-8')
    return fixes > 0, fixes


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_need_braces",
        description=(
            "Fix brace placement on if / else blocks. Standalone short-"
            "circuit if (return/continue/break/throw) collapses to one "
            "line when it fits (Tier 1); otherwise braces are added "
            "(Tier 2). Non-short-circuit bodies always get braces. "
            "if/else pairs always brace both branches."
        ),
    )

    total = 0
    modified = 0
    total_fixes = 0
    for jf in iter_target_files(args):
        total += 1
        changed, fixes = process_file(jf)
        if changed:
            modified += 1
            total_fixes += fixes
            print(f"  Fixed {fixes:3d} in: {jf}")

    print(f"\nProcessed {total} files, modified {modified}, "
          f"{total_fixes} short-circuit fixes applied.")


if __name__ == '__main__':
    main()
