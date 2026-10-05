"""First-run credential setup and local credential loading."""

import os

from rune import store, theme
from rune.prompts import ask_password
from rune.ui import get_console


def load_saved_credentials() -> None:
    """Load saved credentials into the process environment without printing them."""
    credentials = store.read_credentials()
    if credentials.get("github_token") and not os.environ.get("GITHUB_TOKEN"):
        os.environ["GITHUB_TOKEN"] = credentials["github_token"]
    if credentials.get("gemini_api_key") and not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = credentials["gemini_api_key"]


def ensure_credentials() -> bool:
    """Load credentials or guide the player through first-run credential setup."""
    load_saved_credentials()
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GEMINI_API_KEY"):
        return True

    console = get_console()
    console.print(theme.credentials_header)
    github_token = os.environ.get("GITHUB_TOKEN") or ask_password(theme.ask_github_token)
    if not github_token or not github_token.strip():
        console.print(theme.credentials_cancelled)
        return False
    gemini_api_key = os.environ.get("GEMINI_API_KEY") or ask_password(theme.ask_gemini_key)
    if not gemini_api_key or not gemini_api_key.strip():
        console.print(theme.credentials_cancelled)
        return False

    store.save_credentials(github_token.strip(), gemini_api_key.strip())
    os.environ["GITHUB_TOKEN"] = github_token.strip()
    os.environ["GEMINI_API_KEY"] = gemini_api_key.strip()
    console.print(theme.credentials_saved)
    return True
