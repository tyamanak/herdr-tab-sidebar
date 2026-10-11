#!/usr/bin/env python3
"""Entry point for the Herdr manifest hooks and actions. See README.md."""
import sys

# Checked before anything else is imported, and this file avoids newer syntax,
# so an old interpreter reports the reason instead of a syntax error.
if sys.version_info < (3, 9):
    sys.stderr.write(
        "tab-sidebar: needs Python 3.9 or later, but python3 is %s (%s)\n"
        % (sys.version.split()[0], sys.executable)
    )
    sys.exit(2)

from tab_sidebar import cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(cli.main())
