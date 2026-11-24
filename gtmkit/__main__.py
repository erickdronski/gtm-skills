"""``python3 -m gtmkit`` runs the same front door as the ``gtmkit`` command."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(prog="python3 -m gtmkit"))
