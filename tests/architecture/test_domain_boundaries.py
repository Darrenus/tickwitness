"""Keep domain and application dependencies pointed inward."""

import ast
import sys
from pathlib import Path


def assert_import_boundary(layer: str, allowed: tuple[str, ...]) -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "tickwitness" / layer
    modules = sorted(root.rglob("*.py"))
    assert modules, "The architecture check must inspect actual domain modules"
    violations = []
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = ["tickwitness", *module.relative_to(root.parent).parts[:-1]]
                    anchor = package[: len(package) - node.level + 1]
                    if node.module:
                        imported = [".".join([*anchor, node.module])]
                    else:
                        imported = [".".join([*anchor, alias.name]) for alias in node.names]
                elif node.module:
                    imported = [node.module]
            for name in imported:
                if name.split(".", 1)[0] in sys.stdlib_module_names:
                    continue
                if any(name == prefix or name.startswith(prefix + ".") for prefix in allowed):
                    continue
                violations.append(f"{module.relative_to(root)}:{node.lineno}: {name}")
    assert not violations, f"{layer} dependency boundary violated:\n" + "\n".join(violations)


def test_domain_depends_only_on_stdlib_and_domain_modules() -> None:
    assert_import_boundary("domain", ("tickwitness.domain",))


def test_application_depends_on_ports_and_domain_not_storage_adapters() -> None:
    assert_import_boundary("application", ("tickwitness.application", "tickwitness.domain"))
