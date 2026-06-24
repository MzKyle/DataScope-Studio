from __future__ import annotations

import argparse
import os
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
        workspace.heartbeat_job(job_id, token)


if __name__ == "__main__":
    main()
