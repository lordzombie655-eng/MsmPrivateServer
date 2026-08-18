#!/usr/bin/env python3
"""
Launcher multi-instancia para My Singing Monsters Private Server.
Cada instancia = una "versión" / servidor diferente (puertos, server_id, jugadores y datos propios).

Uso:
  python multi_instance.py

Edita INSTANCES abajo o crea carpetas en instances/ con su propio Config.json
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Define aquí las instancias (cada una actúa como servidor distinto)
# Puedes añadir más copiando el bloque y cambiando puertos / server_id / carpeta
INSTANCES = [
    {
        "name": "MSM_Main",
        "config": {
            "host": "0.0.0.0",
            "http_ports": [5050],
            "server_ip": "auto",
            "game_port": 9933,
            "server_id": 1,
            "max_players": 30,
            "data_dir": "Data",
            "players_dir": "players/main",
            "files_folder": "Files",
            "log_level": "info",
            "server_name": "MSM Private - Main",
        },
    },
    {
        "name": "MSM_Alt1",
        "config": {
            "host": "0.0.0.0",
            "http_ports": [5051],
            "server_ip": "auto",
            "game_port": 9934,
            "server_id": 2,
            "max_players": 15,
            "data_dir": "Data",
            "players_dir": "players/alt1",
            "files_folder": "Files",
            "log_level": "info",
            "server_name": "MSM Private - Alt 1",
        },
    },
    {
        "name": "MSM_Alt2",
        "config": {
            "host": "0.0.0.0",
            "http_ports": [5052],
            "server_ip": "auto",
            "game_port": 9935,
            "server_id": 3,
            "max_players": 10,
            "data_dir": "Data",
            "players_dir": "players/alt2",
            "files_folder": "Files",
            "log_level": "info",
            "server_name": "MSM Private - Alt 2",
        },
    },
    {
        "name": "MSM_Test",
        "config": {
            "host": "0.0.0.0",
            "http_ports": [5053],
            "server_ip": "auto",
            "game_port": 9936,
            "server_id": 4,
            "max_players": 5,
            "data_dir": "Data",
            "players_dir": "players/test",
            "files_folder": "Files",
            "log_level": "info",
            "server_name": "MSM Private - Test",
        },
    },
]


def ensure_instance_dirs(inst):
    players = BASE / inst["config"]["players_dir"]
    players.mkdir(parents=True, exist_ok=True)
    data = BASE / inst["config"]["data_dir"]
    data.mkdir(parents=True, exist_ok=True)
    files = BASE / inst["config"].get("files_folder", "Files")
    files.mkdir(parents=True, exist_ok=True)


def write_config(inst, workdir: Path):
    cfg_path = workdir / "Config.json"
    # merge with sensible defaults
    full = {
        "force_empty_manifest": True,
        "cors_origins": ["*"],
        "cors_credentials": False,
        "token_ttl": 900,
        "auth_ttl": 1200,
        "login_ttl": 7200,
    }
    full.update(inst["config"])
    cfg_path.write_text(json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg_path


def main():
    processes = []
    print("=" * 60)
    print("MSM Private Server - Multi Instance Launcher")
    print("=" * 60)

    for inst in INSTANCES:
        name = inst["name"]
        workdir = BASE / "instances" / name
        workdir.mkdir(parents=True, exist_ok=True)

        # symlink or copy modules + Data so each instance can find them
        # We run from BASE and force NPS_BASE_DIR / cwd via env + config paths
        ensure_instance_dirs(inst)
        cfg = write_config(inst, workdir)

        env = os.environ.copy()
        env["NPS_BASE_DIR"] = str(workdir)
        # Also point Python path so imports work
        env["PYTHONPATH"] = str(BASE) + os.pathsep + env.get("PYTHONPATH", "")

        # Create minimal stubs so locate_base finds Config.json
        # The real Data and modules live in BASE; config uses relative paths from workdir
        # To make relative paths resolve, we put relative paths that go up (..)
        # Simpler: make data_dir and players_dir absolute in the written config
        abs_cfg = json.loads(cfg.read_text(encoding="utf-8"))
        abs_cfg["data_dir"] = str((BASE / abs_cfg["data_dir"]).resolve())
        abs_cfg["players_dir"] = str((BASE / abs_cfg["players_dir"]).resolve())
        abs_cfg["files_folder"] = str((BASE / abs_cfg.get("files_folder", "Files")).resolve())
        cfg.write_text(json.dumps(abs_cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        # Symlink the python modules into workdir? Or just run server.py from BASE
        cmd = [sys.executable, str(BASE / "server.py")]
        print(f"[{name}] starting on ports {abs_cfg['http_ports']}  server_id={abs_cfg['server_id']}  max_players={abs_cfg['max_players']}")
        print(f"         Config: {cfg}")
        p = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        processes.append((name, p))

    print("-" * 60)
    print(f"Arrancadas {len(processes)} instancias. Ctrl+C para detener todas.")
    print("-" * 60)

    try:
        while True:
            for name, p in processes:
                if p.poll() is not None:
                    out = p.stdout.read() if p.stdout else ""
                    print(f"[{name}] terminó con código {p.returncode}")
                    if out:
                        print(out[-2000:])
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nDeteniendo instancias...")
        for name, p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for name, p in processes:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        print("Listo.")


if __name__ == "__main__":
    main()
