#!/usr/bin/env python3
"""Fix literal backslash-n and escaped triple-quotes in Python files.

When LLM tools write multi-line Python files incorrectly, they may produce
literal backslash-n (two chars: \\ + n) instead of real newlines.

This script fixes the issue by replacing literal backslash-n that appear
OUTSIDE of string literals with real newlines. Inside string literals,
the backslash-n is preserved.

Usage:
    python3 devkit/fix_python_escapes.py <path_to_python_file> [--in-place]
"""

import argparse
import sys
from pathlib import Path


def fix_python_file(content: str) -> tuple[str, int]:
    """Replace literal backslash-n outside string literals with real newlines."""
    result_lines = []
    changes = 0
    
    for line in content.split('\n'):
        # Track if we are inside a string literal
        fixed_line = ""
        i = 0
        in_string = False
        string_char = None
        
        while i < len(line):
            ch = line[i]
            
            # String start/end
            if ch in ('"', "'") and not in_string:
                in_string = True
                string_char = ch
                fixed_line += ch
                i += 1
                continue
            
            if ch == string_char and in_string:
                # Check for escaped quote (backslash before quote)
                if i > 0 and line[i-1] == '\\':
                    fixed_line += ch
                    i += 1
                    continue
                in_string = False
                string_char = None
                fixed_line += ch
                i += 1
                continue
            
            # Inside string: preserve backslash-n as-is
            if in_string:
                fixed_line += ch
                i += 1
                continue
            
            # Outside string: check for literal backslash-n
            if ch == '\\' and i + 1 < len(line) and line[i+1] == 'n':
                fixed_line += '\n'
                changes += 1
                i += 2
                continue
            
            fixed_line += ch
            i += 1
        
        result_lines.append(fixed_line)
    
    return '\n'.join(result_lines), changes


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix escaped newlines in Python files")
    parser.add_argument("file", nargs="?", help="Python file to fix")
    parser.add_argument("--stdin", action="store_true", help="Read from stdin")
    parser.add_argument("--check", action="store_true", help="Only check, don't fix")
    parser.add_argument("--in-place", "-i", action="store_true", help="Overwrite file in place")
    args = parser.parse_args()
    
    if args.stdin:
        content = sys.stdin.read()
    elif args.file:
        content = Path(args.file).read_text()
    else:
        parser.print_help()
        sys.exit(2)
    
    fixed, changes = fix_python_file(content)
    
    if changes == 0:
        print("OK: No literal backslash-n escapes found.")
        sys.exit(0)
    
    print(f"FOUND: {changes} literal backslash-n escapes to fix.")
    
    if args.check:
        sys.exit(1)
    
    if args.in_place and args.file:
        Path(args.file).write_text(fixed)
        print(f"FIXED: Overwritten {args.file}")
    else:
        sys.stdout.write(fixed)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
