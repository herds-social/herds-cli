"""Secondary entry point for `python -m herds_cli`.

The primary entry point is the `herds` console_script defined in
pyproject.toml, which invokes cli() directly. This module exists so
the package can also be run via `python -m herds_cli`.
"""

from herds_cli.cli import cli

if __name__ == "__main__":
    cli()
