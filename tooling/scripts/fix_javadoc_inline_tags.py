#!/usr/bin/env python3
"""
Reflow Javadoc prose lines that contain inline tags like {@link ...},
{@code ...}, <code>...</code>, etc.

The fix_javadoc_reflow.py script intentionally stops a paragraph at any
line beginning with `{@` or `<` to avoid mangling tag-only structures.
This complement reflows paragraphs that mix prose and inline tags but
leave the trailing line >80 chars.

Strategy:
- Find consecutive ` * ` prose lines (anything not matching @tag, <p>,
  <pre>, <ul>, <ol>, <li>, etc.).
- Treat lines starting with `{@link`, `{@code`, `<code>`, or starting
  with prose containing those tags as still-prose.
- Reflow when any line in the run exceeds MAX_LINE chars.

This script is conservative: it does NOT touch <pre>...</pre> blocks,
list items, or @tag descriptions.
"""

import re
import sys
from pathlib import Path

MAX_LINE = 80

# Lines that should never be folded into the prose flow.
BLOCK_TOKENS = (
    '<p>', '<pre>', '</pre>', '<ul>', '</ul>', '<ol>', '</ol>',
    '<table>', '</table>', '<tr>', '</tr>', '<td>', '</td>',
    '<th>', '</th>',
)


def is_prose_line(stripped):
    """Return True if this line is plain Javadoc prose (possibly with
    inline tags). Returns False for tag descriptions, list items,
    block-level HTML, blank comment lines, or comment delimiters.
    Also returns False for lines that contain {@snippet ...} or its
    file= continuation, since those are unbreakable units relying on
    the checkstyle @snippet ignorePattern.
    """
    if not stripped.startswith('* '):
        return False
    content = stripped[2:].strip()
    if not content:
        return False
    if content.startswith('@'):
        return False
    if content.startswith('<li>'):
        return False
    for tok in BLOCK_TOKENS:
        if content.startswith(tok) and len(content) <= len(tok) + 4:
            return False
    if content == '*/':
        return False
    # Skip {@snippet ...} blocks — file/region paths can't be wrapped
    # and rely on the checkstyle @snippet ignorePattern.
    if '{@snippet' in content or content.startswith('file="'):
        return False
    return True


def is_tag_continuation(raw_after_star):
    """Return True if this looks like a @tag continuation line — extra
    spaces after the `* ` prefix indicating alignment with a tag column.
    """
    return raw_after_star.startswith('  ')


def reflow_paragraph(lines, prefix):
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


def needs_reflow(lines, prefix):
    """Return True if any line in the paragraph would exceed MAX_LINE
    when prefixed."""
    for line in lines:
        if len(prefix) + len(line) > MAX_LINE:
            return True
    return False


def process_file(path):
    text = path.read_text(encoding='utf-8')
    original_lines = text.splitlines(True)

    new_lines = []
    changed = False
    i = 0
    in_pre = False
    in_javadoc = False

    while i < len(original_lines):
        line = original_lines[i]
        rstripped = line.rstrip('\n').rstrip('\r')
        stripped = rstripped.strip()

        if stripped.startswith('/**'):
            in_javadoc = True
        if '*/' in stripped:
            in_javadoc = False or in_javadoc and not stripped.endswith('*/')
            # in_javadoc becomes False after we emit this line below

        if '<pre>' in stripped:
            in_pre = True
        if '</pre>' in stripped:
            in_pre = False
            new_lines.append(line)
            i += 1
            continue

        if in_pre or not in_javadoc or not is_prose_line(stripped):
            new_lines.append(line)
            if stripped.endswith('*/'):
                in_javadoc = False
            i += 1
            continue

        # Determine the prefix (indentation + '* ')
        indent = rstripped[:rstripped.index('*')]
        prefix = indent + '* '
        raw_after_star = stripped[2:] if stripped.startswith('* ') else ''

        if is_tag_continuation(raw_after_star):
            new_lines.append(line)
            i += 1
            continue

        para_texts = []
        para_start = i

        text_first = stripped[2:].strip()
        para_texts.append(text_first)
        i += 1

        while i < len(original_lines):
            l = original_lines[i].rstrip('\n').rstrip('\r')
            s = l.strip()

            if not is_prose_line(s):
                break
            raw_next = s[2:] if s.startswith('* ') else ''
            if is_tag_continuation(raw_next):
                break
            text_n = s[2:].strip()
            para_texts.append(text_n)
            i += 1

        if needs_reflow(para_texts, prefix) and len(para_texts) > 0:
            reflowed = reflow_paragraph(para_texts, prefix)
            new_lines.extend(reflowed)
            if len(reflowed) != len(para_texts):
                changed = True
            else:
                for j, rl in enumerate(reflowed):
                    if rl != original_lines[para_start + j]:
                        changed = True
                        break
        else:
            for j in range(para_start, i):
                new_lines.append(original_lines[j])

    if changed:
        path.write_text(''.join(new_lines), encoding='utf-8')
    return changed


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_javadoc_inline_tags",
        description=(
            "Reflow Javadoc paragraphs that contain inline tags "
            "({@link}, <code>, etc.) but are still prose. Catches "
            "the cases fix_javadoc_reflow.py intentionally skips."
        ),
    )

    total = 0
    modified = 0
    for jf in iter_target_files(args):
        total += 1
        if process_file(jf):
            modified += 1
            print(f"  Fixed: {jf}")

    print(f"\nProcessed {total} files, modified {modified}.")


if __name__ == '__main__':
    main()
