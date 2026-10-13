#!/usr/bin/env python3
"""A fake ``vpncmd`` used by the helper unit tests.

It records the exact ``argv`` it received (and the contents of any ``/IN`` file)
to the path in ``FAKE_VPNCMD_RECORD`` as a JSON lines file, then prints a canned
response.  This lets the tests prove that secret values never reach ``argv`` and
that validation happens before execution.
"""

import json
import os
import sys


def main() -> int:
    argv = sys.argv[1:]
    command = ""
    in_path = None
    cmd_index = None
    for index, token in enumerate(argv):
        if token == "/CMD":
            cmd_index = index
        elif token.startswith("/IN:"):
            in_path = token[len("/IN:") :]

    in_content = None
    if in_path and os.path.exists(in_path):
        with open(in_path, encoding="utf-8") as stream:
            in_content = stream.read()
        command = in_content.splitlines()[0].split(" ")[0] if in_content.strip() else ""
    elif cmd_index is not None and cmd_index + 1 < len(argv):
        command = argv[cmd_index + 1]

    record_path = os.environ.get("FAKE_VPNCMD_RECORD")
    if record_path:
        with open(record_path, "a", encoding="utf-8") as stream:
            stream.write(
                json.dumps({"argv": argv, "command": command, "in_content": in_content}) + "\n"
            )

    if command.lower() == "failcmd":
        sys.stdout.write("Error occurred. (Error code: 99)\nboom\n")
        return 99

    if in_content is not None:
        for line in in_content.splitlines():
            name = line.split(" ")[0] if line.strip() else ""
            sys.stdout.write(f"VPN Client>{line}\n")
            if "Missing" in line:
                sys.stdout.write("Error occurred. (Error code: 36)\nnope\n")
            else:
                sys.stdout.write(f"{name} command - fake\nItem|Value\n----+-----\nok|yes\n")
                sys.stdout.write("The command completed successfully.\n\n")
        return 0

    sys.stdout.write("Item|Value\n----+-----\nok|yes\nThe command completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
