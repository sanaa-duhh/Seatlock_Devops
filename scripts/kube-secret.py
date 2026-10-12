"""Create the SeatLock runtime Secret from a private env file, passed through stdin.

Local clusters reuse the Compose `.env`. The EKS cluster gets its own generated
`.env.eks`, so cloud and laptop never share credentials. Values are never printed.
"""
import argparse
import json
import os
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONTEXTS = {"minikube", "kind-seatlock", "docker-desktop"}

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--namespace", choices=["seatlock", "seatlock-drill"], default="seatlock")
args = parser.parse_args()

context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
if context in LOCAL_CONTEXTS:
    env_path = ROOT / (".env" if args.namespace == "seatlock" else f".env.{args.namespace}")
elif context.startswith("arn:aws:eks:") and context.endswith(":cluster/seatlock-demo"):
    env_path = ROOT / ".env.eks"
else:
    raise SystemExit(f"Refusing unknown kube context: {context}")

if not env_path.exists():
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nADMIN_TOKEN={secrets.token_hex(32)}\n")

values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line)
password = values["POSTGRES_PASSWORD"]
secret = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {"name": "seatlock-runtime", "namespace": args.namespace},
    "type": "Opaque",
    "stringData": {
        "postgres-password": password,
        "admin-token": values["ADMIN_TOKEN"],
        "database-url": f"postgresql+psycopg://seatlock:{password}@postgres:5432/seatlock",
    },
}
# Server-side apply avoids storing a plaintext last-applied annotation.
subprocess.run(["kubectl", "apply", "--server-side", "-f", "-"], input=json.dumps(secret), text=True, check=True)
print(f"Secret seatlock-runtime applied in {args.namespace} ({env_path.name}).")
