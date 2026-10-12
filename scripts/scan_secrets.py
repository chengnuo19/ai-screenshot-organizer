"""Fail when repository files contain likely API credentials."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__"}
SKIP_FILES = {".env", "config.yaml"}
TEXT_SUFFIXES = {
    ".py", ".md", ".yaml", ".yml", ".toml", ".txt", ".json",
    ".ini", ".cfg",
}
PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    "Zhipu API key": re.compile(
        r"\b[a-fA-F0-9]{16,}\.[A-Za-z0-9_-]{8,}\b"),
    "Assigned secret": re.compile(
        r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]"
        r"(?!YOUR_|REPLACE_|<|\$\{)[A-Za-z0-9._-]{16,}['\"]"),
}


def candidates():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def main() -> int:
    findings = []
    for path in candidates():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {label}")
    if findings:
        print("Potential secrets found:")
        print("\n".join(findings))
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
