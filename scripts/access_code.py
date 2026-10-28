"""Makes a new access code for the demo and its SHA-256 hash.

    python -m scripts.access_code

Put the hash in Render's dashboard as ACCESS_CODE_SHA256, and the code only in the submission
link: https://<site>/?key=<code>. Neither belongs in the repository.
"""

import hashlib
import secrets


def main() -> None:
    code = secrets.token_urlsafe(18)  # 144 random bits
    print(f"Code (for the link only): {code}")
    print(f"SHA-256 (for ACCESS_CODE_SHA256): {hashlib.sha256(code.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
