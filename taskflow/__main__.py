"""Allow `python -m taskflow`."""
import sys
from taskflow.cli import main

if __name__ == "__main__":
    sys.exit(main())
