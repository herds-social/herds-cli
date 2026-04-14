"""
Google OAuth Flow for Herds CLI

Handles interactive Google OAuth authentication with local callback server.
"""

import json
import secrets
import string
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from herds_cli.types import GoogleOAuthConfig


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""

    def __init__(self, *args, oauth_flow=None, **kwargs):
        self.oauth_flow = oauth_flow
        # super().__init__() calls do_GET() synchronously when a request is
        # pending, so self.oauth_flow must be set *before* this call.
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Suppress default HTTP server logs."""
        pass

    def do_GET(self):
        """Handle OAuth callback GET request."""
        try:
            # Parse the callback URL
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)

            # Check for authorization code
            auth_code = query_params.get("code", [None])[0]
            error = query_params.get("error", [None])[0]

            if error:
                self.oauth_flow.error_message = f"OAuth error: {error}"
                self._send_response("Authentication failed. You can close this window.")
                return

            if not auth_code:
                self.oauth_flow.error_message = "No authorization code received"
                self._send_response("Authentication failed. You can close this window.")
                return

            # Exchange code for tokens
            self.oauth_flow.auth_code = auth_code

            # Success response
            self._send_response(
                """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2 style="color: #28a745;">Authentication Successful!</h2>
                <p>You can now close this window and return to the CLI.</p>
                <p style="margin-top: 20px; color: #666;">
                    The authentication process is complete.
                </p>
            </body>
            </html>
            """
            )

        except Exception as e:
            self.oauth_flow.error_message = f"Callback error: {str(e)}"
            self._send_response("An error occurred during authentication.")

    def _send_response(self, message: str):
        """Send HTML response."""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))


@dataclass
class OAuthConfig:
    """Concrete GoogleOAuthConfig implementation for passing OAuth credentials."""

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8080/callback"


class GoogleOAuthFlow:
    """Interactive Google OAuth flow using a local HTTP callback server.

    Accepts a config object satisfying the GoogleOAuthConfig protocol
    (google_client_id, google_client_secret, google_redirect_uri attributes).
    Falls back to HERDS_GOOGLE_* env vars if no config is provided.

    Flow: starts local HTTP server on port 8080 → opens browser for Google
    consent → receives auth code on /callback → exchanges code for ID token
    via Google's token endpoint. Times out after 5 minutes.

    Port 8080 must match the redirect_uri registered in Google Cloud Console.
    If the port is in use, the OAuth flow will fail with an OSError.
    """

    def __init__(self, config: Optional[GoogleOAuthConfig] = None):
        # Google OAuth configuration
        if config:
            self.client_id = config.google_client_id
            self.client_secret = config.google_client_secret
            # Use redirect URI from config if available, otherwise default
            self.redirect_uri = getattr(
                config, "google_redirect_uri", "http://localhost:8080/callback"
            )
        else:
            # Fallback to environment variables if no config provided
            import os

            self.client_id = os.getenv("HERDS_GOOGLE_CLIENT_ID")
            self.client_secret = os.getenv("HERDS_GOOGLE_CLIENT_SECRET")
            self.redirect_uri = os.getenv(
                "HERDS_GOOGLE_REDIRECT_URI", "http://localhost:8080/callback"
            )
        self.scope = "openid email profile"

        # OAuth state
        self.auth_code = None
        self.error_message = None
        self.server = None

    def authenticate(self) -> Optional[str]:
        """
        Perform OAuth authentication flow.

        Returns:
            str: Google ID token if successful, None if failed
        """
        try:
            # Generate state for security
            state = self._generate_state()

            # Start local callback server
            server_thread = threading.Thread(target=self._start_callback_server)
            server_thread.daemon = True
            server_thread.start()

            # Give server time to start
            time.sleep(0.5)

            # Build authorization URL
            auth_url = self._build_auth_url(state)

            # Open browser
            print(f"Opening browser for Google authentication...")
            webbrowser.open(auth_url)

            # Wait for callback
            timeout = 300  # 5 minutes
            start_time = time.time()

            while self.auth_code is None and self.error_message is None:
                if time.time() - start_time > timeout:
                    self.error_message = "Authentication timeout"
                    break
                time.sleep(0.1)

            # Stop server
            if self.server:
                self.server.shutdown()

            if self.error_message:
                print(f"OAuth failed: {self.error_message}")
                return None

            if not self.auth_code:
                print("OAuth failed: No authorization code received")
                return None

            # Exchange code for tokens
            return self._exchange_code_for_token(self.auth_code)

        except Exception as e:
            print(f"OAuth flow error: {str(e)}")
            return None

    def _generate_state(self) -> str:
        """Generate random state parameter for security."""
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(32))

    def _build_auth_url(self, state: str) -> str:
        """Build Google OAuth authorization URL."""
        base_url = "https://accounts.google.com/o/oauth2/v2/auth"

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": self.scope,
            "response_type": "code",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }

        return f"{base_url}?{urllib.parse.urlencode(params)}"

    def _start_callback_server(self):
        """Start local HTTP server for OAuth callback."""
        try:
            # Create handler with reference to this flow
            def handler_class(*args, **kwargs):
                return OAuthCallbackHandler(*args, oauth_flow=self, **kwargs)

            self.server = HTTPServer(("localhost", 8080), handler_class)
            self.server.serve_forever()
        except Exception as e:
            self.error_message = f"Server error: {str(e)}"

    def _exchange_code_for_token(self, auth_code: str) -> Optional[str]:
        """Exchange authorization code for Google ID token."""
        try:
            token_url = "https://oauth2.googleapis.com/token"

            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            }

            # Make POST request
            data_encoded = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(token_url, data=data_encoded)

            with urllib.request.urlopen(req) as response:
                token_data = json.loads(response.read().decode("utf-8"))

            # Return the ID token
            return token_data.get("id_token")

        except Exception as e:
            print(f"Token exchange failed: {str(e)}")
            return None
