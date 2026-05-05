"""RADRILONIUMA MCP unified launcher."""

import sys
from .gateway import main as gateway_main
from .search import main as search_main
from .filesystem import main as filesystem_main
from .protocols import main as protocols_main
from .executor import main as executor_main

SERVERS = {
    "gateway": gateway_main,
    "search": search_main,
    "filesystem": filesystem_main,
    "protocols": protocols_main,
    "executor": executor_main,
}

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in SERVERS:
        print("RADRILONIUMA MCP — Unified Server Launcher")
        print("Usage: radriloniuma <server>")
        for name in SERVERS:
            print(f"  {name}")
        sys.exit(1)
    SERVERS[sys.argv[1]]()

if __name__ == "__main__":
    main()
