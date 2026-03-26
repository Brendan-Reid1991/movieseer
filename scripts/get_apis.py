#!/usr/bin/env python

import argparse
import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Callable, Collection
from configparser import ConfigParser
from functools import wraps
from itertools import chain
from pathlib import Path

if not (containing_folder := Path(__file__).parent).parts[-1] == "scripts":
    raise ValueError(f"Script {__file__} is expected to be in a folder 'scripts/'.")

CONFIG_DIR = containing_folder.parent / "services" / "config"

EXTS = {".xml", ".ini", ".json"}
XML_FIELDS = {"ApiKey"}
INI_FIELDS = {("misc", "api_key")}
JSON_FIELDS = {("main", "apiKey")}


def parse_script_arguments() -> list[str]:
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--exclude", default=None)
    args = parser.parse_args()

    return [args.exclude] if args.exclude else []


CONFIG_PATTERNS: set[str] = {
    "config.xml",
    lambda service: f"{service}.ini",
    "settings.json",
}


def main():
    # exclude = parse_script_arguments()
    exclude = []
    for service in os.listdir(CONFIG_DIR):
        if service in exclude:
            continue
        subdir = CONFIG_DIR / service
        candidates = chain.from_iterable(subdir.glob("*" + ext) for ext in EXTS)


def capture_api(function: Callable[[Path], Collection[str]]) -> Callable[[Path], str]:
    @wraps(function)
    def internal(filepath: Path) -> str:
        output: Collection[str] = function(filepath)
        if len(output) != 1:
            detail = (
                "Output was empty."
                if not output
                else f"Multiple candidates found: {output}"
            )
            raise ValueError(f"API key not found in {filepath}. {detail}")
        return next(iter(output))

    return internal


@capture_api
def parse_xml(filepath: Path) -> Collection[str]:
    tree = ET.parse(filepath)
    root = tree.getroot()
    valid_keys = XML_FIELDS & {child.tag for child in root}
    return {root.find(key).text for key in valid_keys}


@capture_api
def parse_ini(filepath: Path) -> Collection[str]:
    content = filepath.read_text()
    parser = ConfigParser()
    parser.read_string("[_]\n" + content)
    return [
        parser[section][field]
        for section, field in INI_FIELDS
        if parser.has_option(section, field)
    ]


@capture_api
def parse_json(filepath: Path) -> Collection[str]:
    with open(filepath) as f:
        content = json.load(f)
    return [content[section][field] for section, field in JSON_FIELDS]


if __name__ == "__main__":
    main()
