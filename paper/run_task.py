"""Container entrypoint: one scheduled 4h cycle.

Environment:
  PAPER_STATE_S3      s3://bucket/key.db  -> SQLite state is downloaded before and uploaded after the run
                      (conditional upload on the downloaded ETag, so two overlapping runs can never overwrite
                      each other). Unset -> local file PAPER_DB (default /state/paper.db).
  PAPER_CONFIG        path to paper_config.json (default /app/paper_config.json)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   optional; injected from AWS SSM Parameter Store (never in the image)
First run with no state: the database is initialised from PAPER_CONFIG, then the cycle runs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from paper import alerts
from paper.store import Store
from paper.trader import cmd_init, cmd_reconcile, cmd_resume, cmd_run, cmd_status

LOCAL = os.environ.get("PAPER_DB", "/state/paper.db")


def _s3():
    import boto3
    uri = os.environ["PAPER_STATE_S3"]
    bucket, key = uri[5:].split("/", 1)
    return boto3.client("s3"), bucket, key


def download() -> str | None:
    if not os.environ.get("PAPER_STATE_S3"):
        return None
    s3, bucket, key = _s3()
    Path(LOCAL).parent.mkdir(parents=True, exist_ok=True)
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        print("no state in S3 yet: first run", flush=True)
        return "NEW"
    Path(LOCAL).write_bytes(obj["Body"].read())
    return obj["ETag"]


def upload(etag: str | None):
    if not os.environ.get("PAPER_STATE_S3"):
        return
    s3, bucket, key = _s3()
    st = Store(LOCAL)
    st.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # fold the WAL into the main file before copying
    st.db.close()
    body = Path(LOCAL).read_bytes()
    kw = {"IfNoneMatch": "*"} if etag == "NEW" else {"IfMatch": etag}
    s3.put_object(Bucket=bucket, Key=key, Body=body, **kw)
    print(f"state uploaded to s3://{bucket}/{key} ({len(body)} bytes)", flush=True)


def main():
    """Usage: python -m paper.run_task [run|status|reconcile|resume]   (default: run)"""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    cfg = os.environ.get("PAPER_CONFIG", "/app/paper_config.json")
    try:
        etag = download()
        if etag == "NEW" or not Path(LOCAL).exists():
            if cmd != "run":
                raise SystemExit("no state yet: the first scheduled run creates it")
            cmd_init(SimpleNamespace(config=cfg, db=LOCAL))
        a = SimpleNamespace(db=LOCAL, now=None)
        {"run": cmd_run, "status": cmd_status, "reconcile": cmd_reconcile, "resume": cmd_resume}[cmd](a)
        if cmd in ("run", "resume", "reconcile"):
            upload(etag)
    except Exception as e:
        alerts.send(f"[paper] RUN FAILED: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    sys.exit(main())
