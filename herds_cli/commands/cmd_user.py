"""
User management commands for the Herds CLI.

This module contains commands for user authentication, account management,
and session handling.
"""

import click
import getpass
import sys

from herds_cli.output import OutputFormatter
from herds_cli.core.base import (
    get_or_detect_session_email,
    validate_session_exists,
)


@click.group()
def user():
    """User management commands (login, logout, create account, etc.)"""
    pass


@user.command()
@click.option("--email", prompt=True, help="Email address")
@click.option(
    "--password", hide_input=True, help="Password (will prompt if not provided)"
)
@click.option("--show-tokens", is_flag=True, help="Display access/refresh tokens")
@click.option(
    "--client-type",
    type=click.Choice(["web", "mobile"]),
    default="mobile",
    help="Client type: web (cookies) or mobile (tokens)",
    show_default=True,
)
@click.pass_context
def login(ctx, email, password, show_tokens, client_type):
    """Authenticate with the API and save session."""

    # Prompt for password if not provided
    if not password:
        password = getpass.getpass("Password: ")

    api_client = ctx.obj["api_client"]
    session_manager = ctx.obj["session_manager"]
    output_format = ctx.obj["format"]

    try:
        # Check if session already exists
        existing_session = session_manager.load_session(email)

        if existing_session:
            OutputFormatter.print_info(f"Overwriting existing session for {email}...")

        OutputFormatter.print_info(
            f"Logging in as {email} (client_type: {client_type})..."
        )
        result = api_client.login(email, password, client_type)

        # Format success message
        user_data = result.get("user", {})
        session_filename = result.get("session_filename", "unknown")

        OutputFormatter.print_success("Login successful!")
        if client_type == "mobile":
            OutputFormatter.print_success(f"Welcome back, {email}!")
            OutputFormatter.print_info(
                f"Mobile client session saved as: {session_filename}"
            )
        else:
            OutputFormatter.print_success(
                f"Welcome back, {user_data.get('email', email)}!"
            )
            OutputFormatter.print_info(
                f"Web client session saved as: {session_filename}"
            )

        # Show tokens if requested
        if show_tokens:
            OutputFormatter.print_info("Session Auth Data:")
            session_data = session_manager.load_session(email)
            if session_data:
                if client_type == "mobile" and "tokens" in session_data:
                    tokens = session_data["tokens"]
                    for key, value in tokens.items():
                        if key == "access_token":
                            # Truncate long tokens for display
                            display_value = (
                                f"{value[:20]}..." if len(str(value)) > 20 else value
                            )
                            OutputFormatter.print_info(f"  {key}: {display_value}")
                        else:
                            OutputFormatter.print_info(f"  {key}: {value}")
                elif client_type == "web" and "cookies" in session_data:
                    cookies = session_data["cookies"]
                    for key, value in cookies.items():
                        OutputFormatter.print_info(f"  {key}: {value}")

        # Output formatted response
        if output_format != "table":  # table format already printed above
            output = OutputFormatter.format_output(result, output_format)
            if output:  # Only print if there's content
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Login failed: {e}")
        sys.exit(1)


@user.command()
@click.pass_context
def login_google(ctx):
    """Authenticate with Google using interactive OAuth flow.

    This command opens your browser for Google sign-in and handles the complete
    authentication process automatically.

    Usage:
    ./scripts/herds_cli user login-google
    """

    api_client = ctx.obj["api_client"]
    session_manager = ctx.obj["session_manager"]
    output_format = ctx.obj["format"]

    try:
        # Interactive OAuth flow
        OutputFormatter.print_info("Starting Google OAuth flow...")
        OutputFormatter.print_info("Your browser will open for Google sign-in.")

        # Load Google OAuth credentials from the separate JSON file
        google_config = None
        try:
            import json

            with open("./herds-google-oauth-config.json", "r") as f:
                google_config = json.load(f)
        except FileNotFoundError:
            pass  # Will check general config below

        # Extract credentials from Google OAuth format
        google_client_id = None
        google_client_secret = None
        google_redirect_uri = "http://localhost:8080/callback"

        if google_config and "installed" in google_config:
            installed = google_config["installed"]
            google_client_id = installed.get("client_id")
            google_client_secret = installed.get("client_secret")
            if installed.get("redirect_uris"):
                redirect_uri = installed["redirect_uris"][0]
                if redirect_uri == "http://localhost":
                    google_redirect_uri = "http://localhost:8080/callback"
                else:
                    google_redirect_uri = redirect_uri

        # Fall back to general CLI config if Google OAuth config doesn't have credentials
        config = ctx.obj.get("config")
        if not google_client_id and config:
            google_client_id = config.google_client_id
        if not google_client_secret and config:
            google_client_secret = config.google_client_secret

        if not google_client_id or not google_client_secret:
            OutputFormatter.print_error(
                "Google OAuth not configured. Please set HERDS_GOOGLE_CLIENT_ID and "
                "HERDS_GOOGLE_CLIENT_SECRET environment variables, or configure them "
                "in your herds-google-oauth-config.json file."
            )
            OutputFormatter.print_info(
                "Example configuration:\n"
                "{\n"
                '  "google_client_id": "your_google_client_id",\n'
                '  "google_client_secret": "your_google_client_secret"\n'
                "}"
            )
            sys.exit(1)

        # Import here to avoid circular imports
        from ..oauth import GoogleOAuthFlow

        # Create a simple object with the OAuth credentials
        class OAuthConfig:
            def __init__(self, client_id, client_secret, redirect_uri):
                self.google_client_id = client_id
                self.google_client_secret = client_secret
                self.google_redirect_uri = redirect_uri

        oauth_config = OAuthConfig(
            google_client_id, google_client_secret, google_redirect_uri
        )
        oauth_flow = GoogleOAuthFlow(oauth_config)
        id_token = oauth_flow.authenticate()

        if not id_token:
            OutputFormatter.print_error("OAuth flow failed - no ID token received.")
            sys.exit(1)

        OutputFormatter.print_info("OAuth flow completed. Authenticating with Herds...")

        # Authenticate with the ID token
        result = api_client.google_auth(id_token)

        # Format success message
        user_data = result.get("user", {})
        user_email = user_data.get("email", "unknown")
        session_filename = result.get("session_filename", "unknown")

        OutputFormatter.print_success("Google authentication successful!")
        OutputFormatter.print_success(f"Welcome, {user_email}!")
        OutputFormatter.print_info(f"Session saved as: {session_filename}")

        # Output formatted response
        if output_format != "table":  # table format already printed above
            output = OutputFormatter.format_output(result, output_format)
            if output:  # Only print if there's content
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Google authentication failed: {e}")
        sys.exit(1)


@user.command()
@click.option("--email", prompt=True, help="Email address")
@click.option(
    "--password", hide_input=True, help="Password (will prompt if not provided)"
)
@click.pass_context
def create_user(ctx, email, password):
    """Create a new user account (requires HERDS_APP_API_KEY)."""

    # Prompt for password if not provided
    if not password:
        password = getpass.getpass("Password: ")

    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    try:
        OutputFormatter.print_info(f"Creating user account for {email}...")
        result = api_client.create_user(email, password)

        # Format success message
        user_data = result.get("user", {})
        message = result.get("message", "User created successfully")

        OutputFormatter.print_success("User created successfully!")
        OutputFormatter.print_success(
            f"Account created for: {user_data.get('email', email)}"
        )
        OutputFormatter.print_info(f"{message}")

        # Show email verification status
        if user_data.get("email_confirmed_at"):
            OutputFormatter.print_success("Email verified automatically")
            OutputFormatter.print_info(
                f"Next step: Run login command to create a session:\n"
                f"  herds --base-url={ctx.obj['base_url']} user login --email={email}"
            )
        else:
            OutputFormatter.print_warning(
                "Please check your email to verify your account"
            )
            OutputFormatter.print_info(
                f"After email verification, run the login command:\n"
                f"  herds --base-url={ctx.obj['base_url']} user login --email={email}"
            )

        # Output formatted response
        if output_format != "table":  # table format already printed above
            output = OutputFormatter.format_output(result, output_format)
            if output:  # Only print if there's content
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"User creation failed: {e}")
        sys.exit(1)


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def logout(ctx, email):
    """Clear stored session."""
    session_manager = ctx.obj["session_manager"]

    # Handle case where no email provided and no sessions exist
    if not email:
        sessions = session_manager.list_sessions()
        if len(sessions) == 0:
            OutputFormatter.print_warning("No active sessions found.")
            return
        elif len(sessions) == 1:
            email = sessions[0]["email"]
            OutputFormatter.print_info(f"Auto-detected session: {email}")
        else:
            OutputFormatter.print_error(
                "Multiple sessions found. Please specify --email"
            )
            OutputFormatter.print_info("Available sessions:")
            for session in sessions:
                click.echo(f"  • {session['email']}")
            return

    if session_manager.delete_session(email):
        OutputFormatter.print_success(f"Logged out {email}")
    else:
        OutputFormatter.print_warning(f"No session found for {email}")


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def update_password(ctx, email):
    """Update password for authenticated user."""
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    # Get email and validate session exists
    config = ctx.obj["config"]
    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )
    session_data = validate_session_exists(session_manager, email)

    client_type = session_data.get("client_type", "web")
    OutputFormatter.print_info(
        f"Updating password for {email} ({client_type} session)..."
    )

    try:
        # Get new password with confirmation
        OutputFormatter.print_warning("Enter new password (minimum 8 characters):")
        new_password = getpass.getpass("New password: ")

        if len(new_password) < 8:
            OutputFormatter.print_error("Password must be at least 8 characters long.")
            sys.exit(1)

        confirm_password = getpass.getpass("Confirm new password: ")

        if new_password != confirm_password:
            OutputFormatter.print_error("Passwords do not match.")
            sys.exit(1)

        # Attempt password update
        result = api_client.update_password(email, new_password)

        # Clear passwords from memory
        new_password = None
        confirm_password = None

        # Display success message
        OutputFormatter.print_success("Password updated successfully!")
        OutputFormatter.print_success(f"Your password has been changed for {email}")

        if result.get("user_id"):
            OutputFormatter.print_info(f"User ID: {result['user_id']}")

        OutputFormatter.print_warning(
            "Remember to update your password in any saved password managers."
        )

        # Output formatted response if requested
        if output_format != "table":
            output = OutputFormatter.format_output(result, output_format)
            if output:
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Password update failed: {e}")
        sys.exit(1)


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def change_password(ctx, email):
    """Change password for authenticated user (requires current password)."""
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    # Get email and validate session exists
    config = ctx.obj["config"]
    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )
    session_data = validate_session_exists(session_manager, email)

    client_type = session_data.get("client_type", "web")

    # Get refresh token for mobile clients
    refresh_token = None
    if client_type == "mobile":
        tokens = session_data.get("tokens", {})
        refresh_token = tokens.get("refresh_token")

    OutputFormatter.print_info(
        f"Changing password for {email} ({client_type} session)..."
    )

    try:
        # Get current password
        OutputFormatter.print_warning("Enter your current password:")
        current_password = getpass.getpass("Current password: ")

        # Get new password with confirmation
        OutputFormatter.print_warning("Enter new password (minimum 8 characters):")
        new_password = getpass.getpass("New password: ")

        if len(new_password) < 8:
            OutputFormatter.print_error("Password must be at least 8 characters long.")
            sys.exit(1)

        confirm_password = getpass.getpass("Confirm new password: ")

        if new_password != confirm_password:
            OutputFormatter.print_error("Passwords do not match.")
            sys.exit(1)

        # Attempt password change
        result = api_client.change_password(
            email, current_password, new_password, refresh_token
        )

        # Clear passwords from memory
        current_password = None
        new_password = None
        confirm_password = None

        # Display success message
        OutputFormatter.print_success("Password changed successfully!")
        OutputFormatter.print_success(f"Your password has been changed for {email}")

        if result.get("user_id"):
            OutputFormatter.print_info(f"User ID: {result['user_id']}")

        OutputFormatter.print_warning(
            "Remember to update your password in any saved password managers."
        )

        # Output formatted response if requested
        if output_format != "table":
            output = OutputFormatter.format_output(result, output_format)
            if output:
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Password change failed: {e}")
        sys.exit(1)


@user.command()
@click.pass_context
def sessions(ctx):
    """List all available session files."""
    session_manager = ctx.obj["session_manager"]
    sessions = session_manager.list_sessions()

    if not sessions:
        OutputFormatter.print_warning("No active sessions found.")
        return

    OutputFormatter.print_info("Available sessions:")
    for session in sessions:
        # Load full session data to get client_type
        full_session = session_manager.load_session(session["email"])
        client_type = (
            full_session.get("client_type", "web") if full_session else "unknown"
        )
        click.echo(f"  • {session['email']} ({client_type}) - {session['filename']}")


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def whoami(ctx, email):
    """Show current user info (requires active session)."""
    session_manager = ctx.obj["session_manager"]

    # Auto-detect session if not specified
    sessions = session_manager.list_sessions()
    if len(sessions) == 0:
        OutputFormatter.print_error("No active sessions found. Please login first.")
        OutputFormatter.print_info("Run: python herds_cli/cli.py user login")
        return
    elif len(sessions) == 1:
        email = sessions[0]["email"]
        OutputFormatter.print_info(f"Using session: {email}")
    else:
        OutputFormatter.print_info("Multiple sessions found:")
        for session in sessions:
            session_data = session_manager.load_session(session["email"])
            if session_data:
                user_data = session_data.get("user_data", {})
                client_type = session_data.get("client_type", "web")
                user_id = user_data.get("id") or user_data.get("user_id", "unknown")
                click.echo(
                    f"  • {session['email']} ({client_type}) - {user_data.get('email', 'unknown')} (ID: {user_id})"
                )
        return

    # Load and display session info
    session_data = session_manager.load_session(email)
    if not session_data:
        OutputFormatter.print_error(f"Failed to load session for {email}")
        return

    client_type = session_data.get("client_type", "web")
    user_data = session_data.get("user_data", {})

    user_id = user_data.get("id") or user_data.get("user_id", "unknown")
    OutputFormatter.print_success(f"Logged in as: {user_data.get('email', email)}")
    OutputFormatter.print_info(f"User ID: {user_id}")
    OutputFormatter.print_info(f"Client type: {client_type}")

    if "created_at" in user_data:
        OutputFormatter.print_info(f"Account created: {user_data['created_at']}")
    if "created_at" in session_data:
        OutputFormatter.print_info(f"Session created: {session_data['created_at']}")

    # Show auth method
    if client_type == "mobile":
        tokens = session_data.get("tokens", {})
        if tokens.get("access_token"):
            OutputFormatter.print_info("Auth method: Bearer token")
    else:
        cookies = session_data.get("cookies", {})
        if cookies:
            OutputFormatter.print_info("Auth method: HTTP cookies")


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def info(ctx, email):
    """Show current user information (requires active session)."""
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    # Get email and validate session exists
    config = ctx.obj["config"]
    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )
    validate_session_exists(session_manager, email)

    try:
        OutputFormatter.print_info(f"Fetching user information for {email}...")
        result = api_client.get_current_user(email)

        # Display success message
        user_data = result.get("user", {})
        OutputFormatter.print_success("User Information:")
        OutputFormatter.print_success(f"Email: {user_data.get('email', 'N/A')}")
        OutputFormatter.print_info(f"User ID: {user_data.get('id', 'N/A')}")
        OutputFormatter.print_info(
            f"Sign-in method: {user_data.get('sign_in_method', 'N/A')}"
        )

        if "created_at" in user_data and user_data["created_at"]:
            OutputFormatter.print_info(f"Account created: {user_data['created_at']}")
        if "last_sign_in_at" in user_data and user_data["last_sign_in_at"]:
            OutputFormatter.print_info(f"Last sign-in: {user_data['last_sign_in_at']}")

        if "settings" in user_data and user_data["settings"]:
            OutputFormatter.print_info("Settings:")
            settings = user_data["settings"]
            if "default_calendar" in settings:
                OutputFormatter.print_info(
                    f"  Default calendar: {settings['default_calendar'] or 'None'}"
                )
            if "sort_by" in settings:
                OutputFormatter.print_info(
                    f"  Sort by: {settings['sort_by'] or 'None'}"
                )
            if "filter_by" in settings:
                OutputFormatter.print_info(
                    f"  Filter by: {settings['filter_by'] or 'None'}"
                )

        # Output formatted response if requested
        if output_format != "table":
            output = OutputFormatter.format_output(result, output_format)
            if output:
                click.echo("")
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Failed to get user information: {e}")
        sys.exit(1)


@user.command()
@click.option("--email", help="Email address (autodetect if only one session)")
@click.pass_context
def usage(ctx, email):
    """Show current usage statistics (requires active session)."""
    session_manager = ctx.obj["session_manager"]
    api_client = ctx.obj["api_client"]
    output_format = ctx.obj["format"]

    # Get email and validate session exists
    config = ctx.obj["config"]
    email = get_or_detect_session_email(
        session_manager, email, show_client_type=True, config=config
    )
    validate_session_exists(session_manager, email)

    try:
        OutputFormatter.print_info(f"Fetching usage statistics for {email}...")
        result = api_client.get_current_usage(email)

        # Display usage information
        monthly = result.get("monthly", {})
        total = result.get("total", {})
        period = result.get("period", "Unknown")
        tier = result.get("tier", "unknown")

        OutputFormatter.print_success("Usage Statistics:")
        OutputFormatter.print_info(f"Subscription Tier: {tier}")
        OutputFormatter.print_info(f"Current Period: {period}")
        OutputFormatter.print_info("")

        # Monthly usage
        OutputFormatter.print_info("Monthly Usage:")
        monthly_used = monthly.get("used", 0)
        monthly_limit = monthly.get("limit")
        monthly_remaining = monthly.get("remaining")

        OutputFormatter.print_info(f"  Images processed: {monthly_used}")
        if monthly_limit is not None:
            OutputFormatter.print_info(f"  Monthly limit: {monthly_limit}")
            if monthly_remaining is not None:
                OutputFormatter.print_info(
                    f"  Remaining this month: {monthly_remaining}"
                )
                # Show usage percentage if limit exists
                if monthly_limit > 0:
                    usage_percent = (monthly_used / monthly_limit) * 100
                    OutputFormatter.print_info(
                        f"  Usage percentage: {usage_percent:.1f}%"
                    )
        else:
            OutputFormatter.print_info("  Monthly limit: Unlimited")

        OutputFormatter.print_info("")

        # Total usage
        OutputFormatter.print_info("Lifetime Usage:")
        total_used = total.get("used", 0)
        total_limit = total.get("limit")
        total_remaining = total.get("remaining")

        OutputFormatter.print_info(f"  Total images processed: {total_used}")
        if total_limit is not None:
            OutputFormatter.print_info(f"  Lifetime limit: {total_limit}")
            if total_remaining is not None:
                OutputFormatter.print_info(f"  Remaining lifetime: {total_remaining}")
                # Show usage percentage if limit exists
                if total_limit > 0:
                    usage_percent = (total_used / total_limit) * 100
                    OutputFormatter.print_info(
                        f"  Usage percentage: {usage_percent:.1f}%"
                    )
        else:
            OutputFormatter.print_info("  Lifetime limit: Unlimited")

        # Show warnings if approaching limits
        if monthly_limit and monthly_remaining is not None and monthly_remaining <= 10:
            OutputFormatter.print_warning(
                f"⚠️  Approaching monthly limit! Only {monthly_remaining} images remaining."
            )

        if total_limit and total_remaining is not None and total_remaining <= 50:
            OutputFormatter.print_warning(
                f"⚠️  Approaching lifetime limit! Only {total_remaining} images remaining."
            )

        # Output formatted response if requested
        if output_format != "table":
            output = OutputFormatter.format_output(result, output_format)
            if output:
                click.echo("")
                click.echo(output)

    except Exception as e:
        OutputFormatter.print_error(f"Failed to get usage statistics: {e}")
        sys.exit(1)
