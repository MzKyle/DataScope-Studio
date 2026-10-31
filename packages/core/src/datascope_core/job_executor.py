from __future__ import annotations

import argparse
import os
import sqlite3
import threading
import traceback
from pathlib import Path

from datascope_core.workspace import JobCancelled, Workspace


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    workspace = Workspace(Path(args.workspace))
    workspace.set_job_worker_pid(args.job, args.token, os.getpid())
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_loop,
        args=(workspace, args.job, args.token, stop),
        daemon=True,
    )
    heartbeat.start()
    try:
        workspace.execute_job(args.job, args.token)
    except JobCancelled:
        raise SystemExit(2)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        stop.set()
        heartbeat.join(timeout=1)


def _heartbeat_loop(
    workspace: Workspace,
    job_id: str,
    token: str,
    stop: threading.Event,
) -> None:
    while not stop.wait(1):
        try:
            workspace.heartbeat_job(job_id, token)
        except sqlite3.OperationalError as error:
            code = getattr(error, 'sqlite_errorcode', -1) & 0xff
            if code not in {5, 6} and not str(error).startswith(  # SQLITE_BUSY / SQLITE_LOCKED
                ('database is locked', 'database table is locked', 'database schema is locked')
            ):
                raise
            # The typed writer owns one publication transaction. Retry after it
            # commits instead of silently losing this thread for the whole job.


if __name__ == "__main__":
    main()
