#!/usr/bin/env python3
"""Fix literal backslash-n and escaped triple-quotes in Python files.

When LLM tools write multi-line Python files incorrectly, they may produce:
- literal backslash-n (two chars: \\ + n) instead of real newlines
- escaped triple quotes \\"\\"\\" instead of real \"\"\"

This script detects and fixes both issues.

Usage:
    python3 devkit/fix_python_escapes.py <path_to_python_file>
    # or: cat file.py | python3 devkit/fix_python_escapes.py --stdin > fixed.py
"""

import argparse
import sys
from pathlib import Path


def fix_python_file(content: str) -> str:
    """Fix literal backslash-n and escaped triple-quotes in Python source."""
    original = content
    
    # Fix 1: escaped triple quotes
    content = content.replace('\\\\\"\"\"', '"""')
    
    # Fix 2: literal backslash-n pairs on lines that are NOT just docstring boundaries
    lines = content.split('\n')
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == '\\\\\"\"\"':
            fixed_lines.append('"""')
        else:
            fixed_lines.append(line.replace('\\n', '\n'))
    
    content = '\n'.join(fixed_lines)
    
    changes = sum(1 for a, b in zip(original, content) if a != b)
    return content, changes


def main():
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
        print("OK: No literal backslash-n or escaped quotes found.")
        sys.exit(0)
    
    print(f"FOUND: {changes} literal escapes to fix.")
    
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
