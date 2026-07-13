# Google Authentication for Herds CLI

This document explains how to set up and use Google authentication with the Herds CLI.

## Prerequisites

1. A Google Cloud Console project with OAuth 2.0 credentials
2. Google+ API enabled in your project

## Setup

### 1. Create OAuth 2.0 Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API
4. Go to "Credentials" in the left sidebar
5. Click "Create Credentials" > "OAuth 2.0 Client IDs"
6. Choose "Desktop application" as the application type
7. Download the credentials JSON file

### 2. Configure the CLI

Set the following environment variables:

```bash
export HERDS_GOOGLE_CLIENT_ID="your_client_id_here"
export HERDS_GOOGLE_CLIENT_SECRET="your_client_secret_here"
```

Download your OAuth 2.0 client credentials from Google Cloud Console and save them as `herds-google-oauth-config.json`:

```json
{
  "installed": {
    "client_id": "your_client_id_here",
    "client_secret": "your_client_secret_here",
    "project_id": "your_project_id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "redirect_uris": ["http://localhost"]
  }
}
```

The CLI will automatically parse this format and extract the necessary credentials.

**Note:** This is separate from the general CLI configuration file (`~/.config/herds/config.json`). The Google OAuth configuration is specific to Google authentication and doesn't affect other CLI settings.

## Usage

### Google Authentication

```bash
./scripts/herds_cli user login-google
```

This will:

1. Open your default web browser
2. Redirect to Google for authentication
3. Start a local server on port 8080 for the OAuth callback
4. Automatically complete authentication and create a session

## Security Notes

- The OAuth flow uses `http://localhost:8080/callback` as the redirect URI
- ID tokens are exchanged for Herds session tokens securely
- Sessions are stored locally with restrictive permissions (600)
- The local callback server only runs during authentication

## Troubleshooting

### "Google OAuth not configured"

Make sure you've set the `HERDS_GOOGLE_CLIENT_ID` and `HERDS_GOOGLE_CLIENT_SECRET` environment variables or configured them in your config file.

### "OAuth flow failed"

- Check that port 8080 is not blocked by firewall
- Ensure your browser can access localhost
- Verify your Google OAuth credentials are correct

### "Authentication timeout"

The OAuth flow times out after 5 minutes. Restart the process if needed.

## Backend Integration

The CLI integrates with the existing `/api/users/auth/google` endpoint in the Herds backend, which:

- Accepts Google ID tokens
- Exchanges them for session tokens
- Creates user accounts automatically on first login
- Supports both mobile and web client types (CLI uses mobile)
