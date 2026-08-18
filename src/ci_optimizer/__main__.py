"""``python -m ci_optimizer`` entry point."""

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
