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
                # Find base indent
                if '(' in method_part.strip():
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

        # Case 3: Method/constructor ending with ') {'
        elif stripped.endswith(') {'):
            needs_allman = True
            if '(' in stripped:
                brace_indent = indent
            else:
                brace_indent = find_base_indent(
                    lines, i, indent)

        # Case 4: Throws on a continuation line ending with '{'
        # e.g. line is "        throws SQLException {"
        elif re.match(r'^\s*throws\s+[\w.,\s<>\[\]]+\{$',
                      right_stripped):
            needs_allman = True
            brace_indent = find_base_indent(lines, i, indent)

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
