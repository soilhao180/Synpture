from __future__ import annotations

import os
from pathlib import Path

from src.application import PipelineOrchestrator
from src.config import load_settings
from src.presentation.web_app import create_web_app
from src.server_boot import create_uvicorn_server, resolve_server_port


def main() -> None:
    host = os.getenv("SYNPTURE_HOST", "127.0.0.1")
    preferred_port = int(os.getenv("SYNPTURE_PORT", "8000"))
    port = resolve_server_port(host, preferred_port)

    if port != preferred_port:
        print(f"端口 {preferred_port} 已被占用，已自动切换到 http://{host}:{port}/")
    else:
        print(f"Synpture 工作台已启动：http://{host}:{port}/")

    create_uvicorn_server(create_web_app(), host=host, port=port).run()


app = create_web_app()


def find_resume_candidate(output_root: Path, current_run_dir: str | None = None) -> dict[str, str] | None:
    orchestrator = PipelineOrchestrator(load_settings())
    return orchestrator.find_resume_candidate(output_root, current_run_dir)


def find_resume_candidate_for_run_dir(run_dir: Path) -> str:
    orchestrator = PipelineOrchestrator(load_settings())
    return orchestrator.detect_recovery_state(run_dir)


if __name__ == "__main__":
    main()
