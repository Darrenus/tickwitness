#!/usr/bin/env python3
"""Check local document links, stable story IDs, and Sprint capacity.

This validates the planning repository. It does not test the planned product.
Run from any directory with Python 3; no third-party dependencies are required.
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    errors = []
    documents = sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in {".git", "node_modules", ".venv"} for part in path.parts)
    )
    links = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^\n)]+)\)", text):
            target = target.strip().split(' "', 1)[0].strip("<>")
            if target.startswith("#") or urlsplit(target).scheme:
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not relative:
                continue
            links += 1
            destination = (path.parent / relative).resolve()
            if not destination.is_relative_to(ROOT):
                errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            elif not destination.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing local link: {target}")

    backlog = (ROOT / "docs/planning/sprint-backlog.md").read_text(encoding="utf-8")
    sections = list(re.finditer(r"^## S(\d+) — .+$", backlog, re.MULTILINE))
    numbers = [int(match.group(1)) for match in sections]
    if numbers != list(range(1, 25)):
        errors.append(f"Expected S1-S24 exactly once and in order; found {numbers}")
    seen = set()
    planned_hours = 0
    for index, section in enumerate(sections):
        sprint = int(section.group(1))
        end = sections[index + 1].start() if index + 1 < len(sections) else len(backlog)
        body = backlog[section.end() : end]
        full_rows = re.findall(r"^\| S\d{2}-\d{2} /[^\n]+$", body, re.MULTILINE)
        hours = 0
        for row in full_rows:
            story = row.split(" /", 1)[0].lstrip("| ")
            if story in seen:
                errors.append(f"Duplicate story ID: {story}")
            seen.add(story)
            if int(story[1:3]) != sprint:
                errors.append(f"{story} is in the wrong Sprint: S{sprint}")
            estimate = re.search(r"\| [SML] / (?:最多 )?(\d+)h \|", row)
            if not estimate:
                errors.append(f"{story}: missing parseable hour estimate")
                continue
            amount = int(estimate.group(1))
            hours += amount
            if amount > 16:
                errors.append(f"{story}: exceeds the 16h story limit")
        if not full_rows:
            errors.append(f"S{sprint}: no stories")
        if hours > 35:
            errors.append(f"S{sprint}: {hours}h exceeds 35h planned capacity")
        planned_hours += hours

    if "Apache License" not in (ROOT / "LICENSE").read_text(encoding="utf-8"):
        errors.append("LICENSE does not contain the selected Apache license")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(documents)} documents, {links} local links, "
        f"{len(sections)} Sprints, {len(seen)} unique stories, "
        f"{planned_hours}h planned work + {15 * len(sections)}h ongoing quality budget."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
