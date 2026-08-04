"""Tests for the shebang rewriters in pack.relocate."""

import tempfile
import unittest
from pathlib import Path

from pack.relocate import bash_shebang_add, python_shebang_add


class TestShebangs(unittest.TestCase):

    def test_python_shebang_prepended(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "tool.py"
            script.write_text("print('hola')\n", encoding="utf-8")
            python_shebang_add(script)
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                "#!/usr/bin/env python3\nprint('hola')\n",
            )

    def test_bash_shebang_prepended(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "tool.sh"
            script.write_text("echo hola\n", encoding="utf-8")
            bash_shebang_add(script)
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                "#!/usr/bin/env bash\necho hola\n",
            )

    def test_python_shebang_preserves_body_bytes(self):
        # -- The rewrite only PREPENDS: the original body must survive
        # -- untouched (including unicode)
        body = "# comentario con acentos: añadió\nx = 1\n"
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "tool.py"
            script.write_text(body, encoding="utf-8")
            python_shebang_add(script)
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                "#!/usr/bin/env python3\n" + body,
            )


if __name__ == "__main__":
    unittest.main()
