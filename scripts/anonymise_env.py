#! /usr/bin/env python3

from pathlib import Path
import re
import os

def read(path: Path) -> list[str]:
    with open(path,"r") as f:
        environment = f.readlines()
    return environment

def parse_line(line: str) -> str:
    if match:=re.match(r"(\w+)=.*", line):
        name = match.groups()[0]
        return f"{name}=...\n"
    return line


def main():
    current_dir = Path(__file__).parent
    root = current_dir.parent
    if not os.path.exists(root / ".env"):
        raise ValueError(f"Implicit root {root} does not contain a .env file.")
    with open(root / ".env.example", "w+") as new_env:
        for line in read(root / ".env"):
            new_env.write(parse_line(line))


if __name__ == "__main__":
    main()



