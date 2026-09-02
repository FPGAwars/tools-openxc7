"""Tests for the body rewrite make-pre-release-stable does on promotion.

build-pre-release writes the body for a PRE-release, so it ends with a
note saying the release will be deleted in a few days. Promotion drops
that section -- and only it -- from the body of the release it publishes.

The workflow carries the program inline, so the tests run THAT program,
extracted from the file: a change to the workflow is a change to what is
tested.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github/workflows/make-pre-release-stable.yaml"

BODY = """\
openXC7 toolchain — 2026-08-30. Validated by CI (package gate and
regression suite on the three platforms).

### On-demand chipdb
The three packages ship **no chipdb**: their `chipdb/` directory
holds a README.txt.

### Build info
**`apio-openxc7-linux-x86-64-20260830.tgz`**
```json
{
  "package-version": "0.9.3",
  "note": "### Pre-release note is not a heading here"
}
```

### Pre-release note
This daily release was created as a pre-release and will be deleted
after a few days.
* To KEEP it around for longer testing: uncheck `Set as a
  pre-release` (no side effects — it just survives the cleanup).
* To PUBLISH it (after testing it for real): run the
  `make-pre-release-stable` workflow with this tag (verifies the assets,
  marks the release stable + latest), then update apio's
  remote-config by hand (apio#927).
"""


def program() -> str:
    """The inline python of the 'Drop the pre-release note' step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    snippet = text.split("<<'PYTRIM'", 1)[1].rsplit("PYTRIM", 1)[0]
    # The workflow indents it inside a YAML block scalar.
    return textwrap.dedent(snippet)


def trim(body: str) -> str:
    """Run the program over *body*; return the rewritten body, or the
    original when the program decided there was nothing to drop."""
    with tempfile.TemporaryDirectory() as scratch:
        source = Path(scratch) / "body.md"
        target = Path(scratch) / "notes.md"
        with open(source, "w", encoding="utf-8", newline="") as out:
            out.write(body)
        result = subprocess.run(
            [sys.executable, "-", str(source), str(target)],
            input=program(), capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        if not target.exists():
            return body
        with open(target, encoding="utf-8", newline="") as written:
            return written.read()


class ReleaseBodyTests(unittest.TestCase):
    def test_the_pre_release_note_goes_and_nothing_else_does(self):
        trimmed = trim(BODY)
        self.assertNotIn("### Pre-release note\n", trimmed)
        self.assertNotIn("will be deleted", trimmed)
        # Everything above it, to the byte -- including the json block,
        # which mentions the words without being that section.
        self.assertEqual(
            trimmed,
            BODY.split("\n### Pre-release note")[0].rstrip("\n") + "\n")
        self.assertIn("is not a heading here", trimmed)

    def test_promoting_twice_changes_nothing(self):
        once = trim(BODY)
        self.assertEqual(trim(once), once)

    def test_a_body_without_the_section_is_left_alone(self):
        body = "openXC7 toolchain — 2026-08-30.\n\n### Build info\nnone\n"
        self.assertEqual(trim(body), body)

    def test_a_section_after_it_survives(self):
        """The section is last today; the rewrite must not assume it."""
        body = (BODY.rstrip("\n")
                + "\n\n### Signatures\nsigned by the release job\n")
        trimmed = trim(body)
        self.assertNotIn("### Pre-release note\n", trimmed)
        self.assertNotIn("will be deleted", trimmed)
        self.assertTrue(trimmed.endswith(
            "### Signatures\nsigned by the release job\n"), trimmed)

    def test_a_body_with_crlf_keeps_its_line_endings(self):
        """A body edited in the browser comes back with CRLF."""
        trimmed = trim(BODY.replace("\n", "\r\n"))
        self.assertNotIn("will be deleted", trimmed)
        self.assertIn("### Build info\r\n", trimmed)
        # every newline is a CRLF: no bare LF survives the rewrite
        self.assertNotIn("\n", trimmed.replace("\r\n", ""))


if __name__ == "__main__":
    unittest.main()
