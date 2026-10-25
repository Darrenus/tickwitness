#!/usr/bin/env python3
"""Export planned Sprint stories as JSON without changing GitHub.

The Markdown backlog owns acceptance intent. GitHub issues own execution state.
The export is deterministic and contains no credentials or user market data.
"""

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "docs/planning/sprint-backlog.md"


def export():
    text = (ROOT / SOURCE).read_text(encoding="utf-8")
    headings = list(re.finditer(r"^## S(\d+) — (.+)$", text, re.MULTILINE))
    sprints = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[match.end():end].strip()
        # The final Sprint is followed by shared process documentation.
        section = section.split("\n## 持续、跨 Sprint 的工作", 1)[0].strip()
        stories = []
        for row in section.splitlines():
            if not re.match(r"^\| S\d{2}-\d{2} /", row):
                continue
            columns = [column.strip() for column in row.strip().strip("|").split("|")]
            if len(columns) != 4:
                raise ValueError(f"Cannot parse story table: {row}")
            identifier, epics = columns[0].split(" / ", 1)
            estimate = re.search(r"(\d+)h", columns[2])
            stories.append({
                "id": identifier,
                "epics": re.findall(r"E\d{2}", epics),
                "description": columns[1],
                "estimate_hours": int(estimate.group(1)),
                "acceptance": columns[3],
            })
        sprints.append({
            "number": int(match.group(1)),
            "title": match.group(2),
            "source": SOURCE,
            "section_markdown": section,
            "stories": stories,
        })
    return {"schema_version": 1, "status": "planned", "sprints": sprints}


if __name__ == "__main__":
    json.dump(export(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
