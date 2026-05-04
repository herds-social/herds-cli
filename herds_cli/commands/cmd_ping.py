"""
Ping command — verify the Herds server is reachable and show its
deployment identity (env, Supabase ref, Mongo DB, git SHA).

The /ping endpoint is unauthenticated and always returns HTTP 200,
so this command works without a session. Exit code reflects only
HTTP reachability — the body is rendered for inspection but does
not influence success/failure. Callers that need finer-grained
health checks (e.g. Mongo connectivity) can parse the JSON output.
"""

import click

from herds_cli.core.base import APIResponseHandler, CommandBase
from herds_cli.core.exceptions import APIRequestError
from herds_cli.output import OutputFormatter
from herds_cli.types import PingResponse


@click.command()
@click.pass_context
def ping(ctx: click.Context) -> None:
    """Ping the Herds server and show its deployment identity."""
    cmd = CommandBase(ctx)
    url = f"{cmd.api_client.base_url}/ping"
    response = cmd.api_client._make_request("GET", url)

    if response.status_code != 200:
        APIResponseHandler.handle_error_response(response, f"GET {url}")
        raise APIRequestError(
            f"Ping failed: HTTP {response.status_code}",
            status_code=response.status_code,
        )

    try:
        data: PingResponse = response.json()
    except Exception as exc:
        OutputFormatter.print_error("Failed to parse ping response as JSON.")
        raise APIRequestError(
            "Ping failed: invalid JSON response",
            status_code=response.status_code,
        ) from exc
    _render(data, cmd.output_format)

    exit_code = _evaluate_ping(data)
    if exit_code != 0:
        ctx.exit(exit_code)


def _render(data: PingResponse, output_format: str) -> None:
    """Print the ping payload.

    JSON output passes the dict through unchanged so machine consumers
    see real ``null`` values. Text output renders each field on stderr
    via print_info, substituting an em-dash for ``None`` because the
    default ``str(None)`` rendering reads as a literal "None" word.
    """
    if output_format == "json":
        APIResponseHandler.format_and_output(data, output_format)
        return
    for key, value in data.items():
        display_value = "—" if value is None else value
        OutputFormatter.print_info(f"  {key}: {display_value}")


def _evaluate_ping(data: PingResponse) -> int:
    """Return the process exit code for a /ping response.

    Policy: **always 0 on HTTP 200**. The caller has already verified
    the request reached the server; this function intentionally ignores
    the body so ``herds ping`` reports only reachability. Scripts that
    care about Mongo connectivity or deployment identity can parse the
    JSON output themselves and apply their own predicates.
    """
    del data  # body intentionally ignored; signature kept for policy evolution
    return 0
