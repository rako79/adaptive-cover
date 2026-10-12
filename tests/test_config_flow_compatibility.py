"""Tests guarding Home Assistant options-flow API compatibility."""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]
CONFIG_FLOW_PATH = ROOT / "custom_components" / "adaptive_cover" / "config_flow.py"


class OptionsFlowCompatibilityTests(unittest.TestCase):
    """Prevent restoring the removed manual config-entry injection pattern."""

    @classmethod
    def setUpClass(cls) -> None:
        """Parse the config flow without requiring Home Assistant in the test venv."""
        cls.tree = ast.parse(CONFIG_FLOW_PATH.read_text(encoding="utf-8"))

    def test_options_flow_factory_uses_no_constructor_arguments(self) -> None:
        """Let Home Assistant attach the config entry after flow construction."""
        handler_class = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ConfigFlowHandler"
        )
        factory = next(
            node
            for node in handler_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "async_get_options_flow"
        )
        returned_call = next(
            node.value
            for node in ast.walk(factory)
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
        )

        self.assertEqual(ast.unparse(returned_call.func), "OptionsFlowHandler")
        self.assertEqual(returned_call.args, [])
        self.assertEqual(returned_call.keywords, [])

    def test_options_flow_does_not_assign_config_entry(self) -> None:
        """Use the read-only config_entry property introduced by Home Assistant."""
        options_class = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OptionsFlowHandler"
        )
        forbidden_assignments = [
            node
            for node in ast.walk(options_class)
            if isinstance(node, ast.Assign | ast.AnnAssign)
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "config_entry"
        ]

        self.assertEqual(forbidden_assignments, [])


if __name__ == "__main__":
    unittest.main()
