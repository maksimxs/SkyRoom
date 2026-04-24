from __future__ import annotations

import sys


ROLE_FLAG = "--skyroom-role"


def _extract_role(argv: list[str]) -> tuple[str, list[str]]:
    cleaned: list[str] = []
    role = "launcher"
    skip_next = False
    for index, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg == ROLE_FLAG and index + 1 < len(argv):
            role = argv[index + 1].strip().lower() or "launcher"
            skip_next = True
            continue
        if arg.startswith(f"{ROLE_FLAG}="):
            role = arg.split("=", 1)[1].strip().lower() or "launcher"
            continue
        cleaned.append(arg)
    return role, cleaned


def main() -> None:
    role, cleaned_argv = _extract_role(sys.argv[1:])
    sys.argv = [sys.argv[0], *cleaned_argv]
    if role == "client":
        from skyroom.client.app import main as client_main

        client_main()
        return
    if role == "server":
        from skyroom.server.app import main as server_main

        server_main()
        return

    from skyroom.client.launcher import main as launcher_main

    launcher_main()


if __name__ == "__main__":
    main()
