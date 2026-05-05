#!/usr/bin/env python3
"""
Reflow Javadoc @tag descriptions (param, return, throws) to fill
lines close to 80 chars. Fixes orphaned short words on continuation
lines.

Handles alignment: @tag continuation lines align with the
description text start, not the tag keyword.
"""

import re
import sys
from pathlib import Path

MAX_LINE = 80


def process_file(filepath):
    """Reflow @param/@return/@throws descriptions in a Java file.

    Returns True if the file was rewritten, False otherwise.
    """
    path = Path(filepath)
    lines = path.read_text(encoding='utf-8').splitlines(True)

    new_lines = []
    changed = False
    i = 0

    while i < len(lines):
        line = lines[i]
        right_stripped = line.rstrip('\n').rstrip('\r')
        stripped = right_stripped.strip()

        # Detect a @tag line inside a Javadoc comment.
        # @return has NO parameter name — its description starts right
        # after `@return`, so try it before the @param/@throws pattern
        # to avoid mistakenly capturing the first description word as
        # a parameter name.
        tag_match = re.match(
            r'^(\s*)\*\s+(@return\s+)(.*)',
            right_stripped)
        if not tag_match:
            # Pattern: " * @param name description" or
            #          " * @throws Type description"
            tag_match = re.match(
                r'^(\s*)\*\s+(@(?:param|throws)\s+\S+\s+)(.*)',
                right_stripped)

        if not tag_match:
            new_lines.append(line)
            i += 1
            continue

        indent = tag_match.group(1)       # leading whitespace
        tag_prefix = tag_match.group(2)   # "@param name " etc
        first_text = tag_match.group(3)   # first line of desc

        # Calculate the continuation alignment
        # " * @param name description"
        # "               ^^^^^^^^^^^" continuation aligns here
        star_prefix = indent + '* '
        full_tag_len = len(star_prefix) + len(tag_prefix)
        cont_prefix = star_prefix + ' ' * len(tag_prefix)

        # Collect all text for this tag description
        texts = [first_text.strip()] if first_text.strip() else []
        i += 1

        # Collect continuation lines (indented past the tag)
        while i < len(lines):
            next_right_stripped = lines[i].rstrip('\n').rstrip('\r')
            next_stripped = next_right_stripped.strip()

            # Stop at blank comment lines, new tags, or end of
            # comment
            if not next_stripped.startswith('*'):
                break
            if next_stripped == '*' or next_stripped == '*/':
                break
            # Check if it's a new tag
            after_star = next_stripped[1:].strip() \
                if len(next_stripped) > 1 else ''
            if after_star.startswith('@'):
                break

            # It's a continuation — extract the text
            if next_stripped.startswith('* '):
                cont_text = next_stripped[2:].strip()
            else:
                cont_text = next_stripped[1:].strip()

            if cont_text:
                texts.append(cont_text)
            else:
                break

            i += 1

        # Check if reflowing is needed.
        # Single-input case: if the line fits within MAX_LINE, emit
        # as-is; otherwise fall through to the wrap logic so the
        # output respects the 80-char ceiling.
        if len(texts) <= 1:
            if not texts:
                new_lines.append(
                    star_prefix + tag_prefix.rstrip() + '\n')
                continue
            single_line_len = len(star_prefix) + len(tag_prefix) \
                + len(texts[0])
            if single_line_len <= MAX_LINE:
                new_lines.append(
                    star_prefix + tag_prefix + texts[0] + '\n')
                continue

        # Join all words and reflow
        all_words = []
        for t in texts:
            all_words.extend(t.split())

        if not all_words:
            new_lines.append(
                star_prefix + tag_prefix.rstrip() + '\n')
            continue

        # First line: star_prefix + tag_prefix + words
        first_max = MAX_LINE - full_tag_len
        result_lines = []
        current = all_words[0]
        word_idx = 1

        while word_idx < len(all_words):
            test = current + ' ' + all_words[word_idx]
            if len(test) <= first_max:
                current = test
                word_idx += 1
            else:
                break

        result_lines.append(
            star_prefix + tag_prefix + current + '\n')

        # Remaining lines: cont_prefix + words
        if word_idx < len(all_words):
            cont_max = MAX_LINE - len(cont_prefix)
            current = all_words[word_idx]
            word_idx += 1

            while word_idx < len(all_words):
                test = current + ' ' + all_words[word_idx]
                if len(test) <= cont_max:
                    current = test
                    word_idx += 1
                else:
                    result_lines.append(
                        cont_prefix + current + '\n')
                    current = all_words[word_idx]
                    word_idx += 1

            result_lines.append(cont_prefix + current + '\n')

        # Check if we actually changed anything
        if len(result_lines) != len(texts):
            changed = True
        else:
            for j, rl in enumerate(result_lines):
                # Compare against what we would have had
                if j == 0:
                    orig = star_prefix + tag_prefix \
                        + texts[0] + '\n'
                else:
                    orig = cont_prefix + texts[j] + '\n'
                if rl != orig:
                    changed = True
                    break

        new_lines.extend(result_lines)

    if changed:
        path.write_text(''.join(new_lines), encoding='utf-8')
        return True
    return False


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _cli import iter_target_files, parse_args

    args = parse_args(
        prog="fix_javadoc_tags",
        description=(
            "Reflow @param / @return / @throws tag descriptions to fill "
            "lines near 80 chars."
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
