"""Prevent explicit infrastructure or third-party imports from entering the domain."""

import ast
import sys
from pathlib import Path


def test_domain_depends_only_on_stdlib_and_domain_modules() -> None:
    domain = Path(__file__).resolve().parents[2] / "src" / "tickwitness" / "domain"
    modules = sorted(domain.rglob("*.py"))
    assert modules, "The architecture check must inspect actual domain modules"
    violations = []
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = [node.module]
            for name in imported:
                if name.split(".", 1)[0] in sys.stdlib_module_names:
                    continue
                if name == "tickwitness.domain" or name.startswith("tickwitness.domain."):
                    continue
                violations.append(f"{module.relative_to(domain)}:{node.lineno}: {name}")
    assert not violations, "Domain dependency boundary violated:\n" + "\n".join(violations)
