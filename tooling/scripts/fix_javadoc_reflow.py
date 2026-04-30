#!/usr/bin/env python3
"""
Reflow Javadoc comment paragraphs to fill lines close to 80 chars.

Detects "awkward" Javadoc lines where a paragraph continuation line
is much shorter than it could be (orphaned words), and reflows the
paragraph to balance line lengths.

Only touches plain Javadoc prose lines (starting with ' * '). Does
NOT touch:
- @param, @return, @throws, @link, @code tags
- Blank comment lines (' *')
- Lines with HTML tags (<p>, <ul>, <li>, <pre>, etc.)
- Lines with code examples or formatting
- The opening '/**' and closing '*/' lines
"""

import re
import sys
from pathlib import Path


MAX_LINE = 80


def is_prose_line(stripped):
    """Return True if this is a plain Javadoc prose line."""
    if not stripped.startswith('* '):
        return False
    content = stripped[2:].strip()
    if not content:
        return False
    # Skip tag lines
    if content.startswith('@'):
        return False
    # Skip HTML tags
    if content.startswith('<') or content.startswith('{@'):
        return False
    # Skip CSOFF/CSON
    if content.startswith('CSOFF') or content.startswith('CSON'):
        return False
    return True


def is_tag_continuation(stripped):
    """Return True if this looks like a continuation of a @tag."""
    if not stripped.startswith('* '):
        return False
    content = stripped[2:].strip()
    # Tag continuation lines are indented with extra spaces
    # after the '* ' prefix
    raw_after_star = stripped[2:] if stripped.startswith('* ') else ''
    if raw_after_star.startswith('  '):
        return True
    return False


def reflow_paragraph(lines, prefix):
    """Reflow a list of prose strings into filled lines.

    Args:
        lines: List of prose text strings (without the prefix).
        prefix: The comment prefix (e.g., '     * ').

    Returns:
        List of reflowed lines (with prefix and newline).
    """
    # Join all words
    words = []
    for line in lines:
        words.extend(line.split())

    if not words:
        return [prefix + line + '\n' for line in lines]

    max_content = MAX_LINE - len(prefix)

    result = []
    current = words[0]

    for word in words[1:]:
        test = current + ' ' + word
        if len(test) <= max_content:
            current = test
        else:
            result.append(prefix + current + '\n')
            current = word

    result.append(prefix + current + '\n')
    return result


def has_short_line(lines, prefix):
    """Check if any line in the paragraph is awkwardly short
    (could fit more words from the next line)."""
    max_content = MAX_LINE - len(prefix)

    for i in range(len(lines) - 1):
        current_len = len(lines[i])
        next_first_word = lines[i + 1].split()[0] \
            if lines[i + 1].split() else ''

        if current_len + 1 + len(next_first_word) <= max_content:
            return True

    return False


def process_file(filepath):
    """Process a single Java file, reflowing awkward Javadoc."""
    path = Path(filepath)
    original_lines = path.read_text(
        encoding='utf-8').splitlines(True)

    new_lines = []
    changed = False
    i = 0
    in_pre = False

    while i < len(original_lines):
        line = original_lines[i]
        right_stripped = line.rstrip('\n').rstrip('\r')
        stripped = right_stripped.strip()

        # Track <pre>...</pre> blocks — never reflow inside
        if '<pre>' in stripped:
            in_pre = True
        if '</pre>' in stripped:
            in_pre = False
            new_lines.append(line)
            i += 1
            continue

        # Check if this is a prose Javadoc line
        if in_pre or not is_prose_line(stripped):
            new_lines.append(line)
            i += 1
            continue

        # Determine the prefix (indentation + '* ')
        indent = right_stripped[:right_stripped.index('*')]
        prefix = indent + '* '

        # Collect consecutive prose lines into a paragraph
        para_texts = []
        para_start = i

        # Add the first line (already confirmed as prose)
        text = stripped[2:].strip()
        para_texts.append(text)
        i += 1

        while i < len(original_lines):
            l = original_lines[i].rstrip('\n').rstrip('\r')
            s = l.strip()

            if is_prose_line(s) and not is_tag_continuation(s):
                text = s[2:].strip()
                para_texts.append(text)
                i += 1
            else:
                break

        # Only reflow if there are multiple lines and
        # the paragraph has awkward short lines
        if len(para_texts) > 1 \
                and has_short_line(para_texts, prefix):
            reflowed = reflow_paragraph(para_texts, prefix)
            new_lines.extend(reflowed)
            if len(reflowed) != len(para_texts):
                changed = True
            else:
                # Check if content differs
                for j, rl in enumerate(reflowed):
                    orig = original_lines[para_start + j]
                    if rl != orig:
                        changed = True
                        break
        else:
            # Keep original lines
            for j in range(para_start, i):
                new_lines.append(original_lines[j])

    if changed:
        path.write_text(''.join(new_lines), encoding='utf-8')
        return True
    return False


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_javadoc_reflow",
        description=(
            "Reflow plain Javadoc prose paragraphs to fill lines near "
            "80 chars. Skips paragraphs that begin with inline tags "
            "({@link}, <code>, etc.) — those are handled by "
            "fix_javadoc_inline_tags.py."
        ),
    )

    total = 0
    modified = 0
    for java_file in iter_target_files(args):
        total += 1
        if process_file(java_file):
            modified += 1
            print(f"  Fixed: {java_file}")

    print(f"\nProcessed {total} files, modified {modified}.")


if __name__ == '__main__':
    main()
