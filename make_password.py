"""Generate an APP_PASSWORD_HASH for the login.

Run:  python make_password.py

The password is typed hidden (never echoed, never stored, never logged). Only
the resulting hash is printed -- put THAT in the server's environment. The
plaintext never leaves your terminal.
"""
import getpass
import sys

from auth import hash_password

if __name__ == "__main__":
    pw = getpass.getpass("New password: ")
    if len(pw) < 12:
        sys.exit("Refusing: use at least 12 characters.")
    if pw != getpass.getpass("Confirm password: "):
        sys.exit("Passwords did not match.")
    print("\nSet this on the server (Coolify -> Environment Variables):\n")
    print(f"APP_PASSWORD_HASH={hash_password(pw)}")
    print("\nAlso set APP_USERNAME=<your username>")
