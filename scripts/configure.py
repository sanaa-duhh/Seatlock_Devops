"""Generate local credentials without printing them. Never invokes AWS."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print("Existing .env preserved.")
else:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nADMIN_TOKEN={secrets.token_hex(32)}\n")
    print("Local credentials created in ignored .env (mode 600). No cloud resources used.")
