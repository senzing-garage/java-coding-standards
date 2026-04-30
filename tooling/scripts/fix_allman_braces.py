#!/usr/bin/env python3
"""
Fix brace placement to Allman style for class/interface/enum/method/
constructor definitions. Also moves 'throws' clauses to their own
line (single-indented from method base).

Leaves control flow blocks (if/else/for/while/try/catch/finally/
switch/synchronized/do/lambda) with same-line braces.
"""

import re
import sys
from pathlib import Path

CONTROL_PREFIXES = [
    'if ', 'if(',
    'else {', 'else{', 'else if ', 'else if(',
    'for ', 'for(',
    'while ', 'while(',
    'do {', 'do{',
    'try {', 'try{', 'try (',
    'catch ', 'catch(',
    'finally {', 'finally{',
    'switch ', 'switch(',
    'synchronized ', 'synchronized(',
]

CONTINUATION_STARTS = [
    '||', '&&', '+', '-', '?', ':', '.',
    '|', '&', '^',
]


def is_control_flow_or_special(stripped):
    """Return True if this line should keep same-line braces."""
    test = stripped
    if test.startswith('}'):
        test = test[1:].strip()

    for prefix in CONTROL_PREFIXES:
        if test.startswith(prefix):
            return True

    if '-> {' in stripped or '->{' in stripped:
        return True

    if test == 'static {' or test == 'static{':
        return True

    if re.search(r'\bnew\s+\w', stripped) and stripped.endswith(') {'):
        return True

    if re.search(r'=\s*\{$', stripped):
        return True

    if re.match(r'^[A-Z_][A-Z_0-9]*\s*\(.*\)\s*\{$', test):
        return True

    return False


def is_class_interface_enum(stripped):
    """Return True if this is a class/interface/enum definition."""
    return bool(re.search(
        r'\b(class|interface|enum)\s+\w+', stripped
    ))


def is_continuation_line(stripped):
    """Return True if this line starts with a continuation operator."""
    for op in CONTINUATION_STARTS:
        if stripped.startswith(op):
            return True
    return False


def find_base_indent(lines, line_idx, current_indent):
    """Scan backward to find the method's base indentation."""
    current_indent_len = len(current_indent)

    for j in range(line_idx - 1, -1, -1):
        prev = lines[j]
        prev_stripped = prev.strip()

        if not prev_stripped or prev_stripped.startswith('*') \
                or prev_stripped.startswith('//') \
                or prev_stripped.startswith('@'):
            continue

        prev_right_stripped = prev.rstrip('\n').rstrip('\r')
        prev_indent = prev_right_stripped[:len(prev_right_stripped)
                                     - len(prev_right_stripped.lstrip())]
        if len(prev_indent) < current_indent_len:
            return prev_indent

    return current_indent


_STRING_LITERAL_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_CHAR_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'")


def find_wrap_opener_indent(lines, start_idx, default_indent):
    """Walk back from start_idx tracking paren balance.

    Returns the indent of the line where cumulative paren balance
    (counting from start_idx's '(' and ')' inclusive) first reaches
    <= 0 — i.e., the line that opens the construct whose closing
    ')' lies on or before start_idx. String and character literals
    are stripped before counting so parens inside strings don't
    affect the balance.

    Falls back to default_indent if no opener is found.
    """
    balance = 0
    for j in range(start_idx, -1, -1):
        ln = lines[j]
        s = ln.strip()
        if not s or s.startswith('//') or s.startswith('*'):
            continue
        code = _STRING_LITERAL_RE.sub('', ln)
        code = _CHAR_LITERAL_RE.sub('', code)
        balance += code.count(')') - code.count('(')
        if balance <= 0:
            line_no_nl = ln.rstrip('\n').rstrip('\r')
            return line_no_nl[:len(line_no_nl)
                              - len(line_no_nl.lstrip())]
    return default_indent


def process_file(filepath):
    """Process a single Java file."""
    path = Path(filepath)
    lines = path.read_text(encoding='utf-8').splitlines(True)

    new_lines = []
    changed = False
    in_block_comment = False

    for i, line in enumerate(lines):
        right_stripped = line.rstrip('\n').rstrip('\r')
        stripped = right_stripped.strip()

        if '/*' in stripped and '*/' not in stripped:
            in_block_comment = True
        if '*/' in stripped:
            in_block_comment = False

        if in_block_comment or stripped.startswith('*') \
                or stripped.startswith('//'):
            new_lines.append(line)
            continue

        # Only process lines ending with ' {' or '\t{'
        if not right_stripped.endswith(' {') \
                and not right_stripped.endswith('\t{'):
            new_lines.append(line)
            continue

        indent = right_stripped[:len(right_stripped) - len(right_stripped.lstrip())]

        # Skip control flow and special blocks
        if is_control_flow_or_special(stripped):
            new_lines.append(line)
            continue

        # Skip continuation lines
        if is_continuation_line(stripped):
            new_lines.append(line)
            continue

        needs_allman = False
        brace_indent = indent

        # Case 1: Class/interface/enum definition
        if is_class_interface_enum(stripped):
            needs_allman = True
            brace_indent = indent

        # Case 2: Method/constructor with ') throws ... {'
        # e.g.: "public void foo() throws Exception {"
        elif re.search(
                r'\)\s+throws\s+[\w.,\s<>\[\]]+\{$', stripped):
            needs_allman = True
            # Extract everything before 'throws'
            m = re.search(r'^(.*\))\s+(throws\s+.+?)\s*\{$',
                          right_stripped)
            if m:
                method_part = m.group(1)  # "...foo()"
                throws_part = m.group(2)  # "throws Exception"
                # Balanced parens => header line; unbalanced
                # (more ')' than '(') => continuation of a wrap
                # opened on a previous line.
                method_part_stripped = method_part.strip()
                if (method_part_stripped.count('(')
                        >= method_part_stripped.count(')')):
                    brace_indent = indent
                else:
                    brace_indent = find_base_indent(
                        lines, i, indent)
                throws_indent = brace_indent + '    '
                new_lines.append(method_part + '\n')
                new_lines.append(throws_indent + throws_part
                                 + '\n')
                new_lines.append(brace_indent + '{\n')
                changed = True
                continue

        # Case 3: Method/constructor or wrapped control-flow
        # condition ending with ') {'.
        elif stripped.endswith(') {'):
            needs_allman = True
            # Balanced parens on this line => method/constructor
            # header (the '(' opens here too); use this line's
            # indent. Unbalanced (more ')' than '(') => the
            # opening '(' is on a previous line, so we're closing
            # a wrapped condition or wrapped parameter list — walk
            # back via paren balance to find the construct opener
            # and align the brace there.
            if stripped.count('(') >= stripped.count(')'):
                brace_indent = indent
            else:
                brace_indent = find_wrap_opener_indent(
                    lines, i, indent)

        # Case 4: Throws on a continuation line ending with '{'
        # e.g. line is "        throws SQLException {"
        elif re.match(r'^\s*throws\s+[\w.,\s<>\[\]]+\{$',
                      right_stripped):
            needs_allman = True
            brace_indent = find_base_indent(lines, i, indent)

        # Case 5: Standalone '{' line — re-align to the wrap-
        # opening line's indent if it's currently sitting at the
        # continuation indent of a wrapped condition. Cleans up
        # buggy output from earlier versions of this script that
        # placed the brace at the continuation indent of the line
        # that closes a wrapped condition or parameter list.
        elif stripped == '{':
            prev_idx = None
            for j in range(i - 1, -1, -1):
                ps = lines[j].strip()
                if (ps and not ps.startswith('//')
                        and not ps.startswith('*')):
                    prev_idx = j
                    break
            if prev_idx is None:
                new_lines.append(line)
                continue
            prev_line = lines[prev_idx].rstrip('\n').rstrip('\r')
            prev_stripped = prev_line.strip()
            # Only act when the prev line closes a wrap (ends
            # with ')' AND has more ')' than '(') AND the brace
            # is at indent >= the prev line's indent. The latter
            # excludes legitimate cases like multi-line method
            # declarations whose brace correctly sits at a
            # smaller indent than the closing-paren line.
            if not prev_stripped.endswith(')'):
                new_lines.append(line)
                continue
            if prev_stripped.count('(') >= prev_stripped.count(')'):
                new_lines.append(line)
                continue
            prev_indent = prev_line[:len(prev_line)
                                    - len(prev_line.lstrip())]
            if len(indent) < len(prev_indent):
                new_lines.append(line)
                continue
            correct_indent = find_wrap_opener_indent(
                lines, prev_idx, prev_indent)
            if correct_indent == indent:
                new_lines.append(line)
                continue
            new_lines.append(correct_indent + '{\n')
            changed = True
            continue

        if needs_allman:
            content = right_stripped.rstrip()
            if content.endswith(' {'):
                content = content[:-2].rstrip()
            elif content.endswith('\t{'):
                content = content[:-2].rstrip()
            elif content.endswith('{'):
                content = content[:-1].rstrip()

            new_lines.append(content + '\n')
            new_lines.append(brace_indent + '{\n')
            changed = True
        else:
            new_lines.append(line)

    if changed:
        path.write_text(''.join(new_lines), encoding='utf-8')
        return True
    return False


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_allman_braces",
        description=(
            "Move opening braces to Allman style for "
            "class/interface/enum/method/constructor definitions and "
            "split throws clauses onto their own line."
        ),
    )

    total_files = 0
    changed_files = 0
    for java_file in iter_target_files(args):
        total_files += 1
        if process_file(java_file):
            changed_files += 1
            print(f"  Fixed: {java_file}")

    print(f"\nProcessed {total_files} files, "
          f"modified {changed_files} files.")


if __name__ == '__main__':
    main()
