"""
Core functionality for the Herds CLI.

This package contains shared base classes (`base`), configuration management
(`config`), and the domain exception hierarchy (`exceptions`). Each submodule
is imported directly by its consumers — there are no re-exports here, since
nothing across `herds_cli/` or `tests/` consumes `from herds_cli.core import X`,
and the eager `from .base import …` re-export previously created an import
cycle through `core.base → herds_cli.api.APIClient → core.exceptions`.
"""
