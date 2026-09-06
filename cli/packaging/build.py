"""빌드 환경에서만 실행. 사용자 배포본은 Python/Node 설치를 요구하지 않는다."""
import hashlib
import json
import platform
import subprocess
import sys
import tomllib
from pathlib import Path

cli = Path(__file__).resolve().parents[1]
layout = "onedir" if "--onedir" in sys.argv else "onefile"
output = cli / "dist" / "portable" if layout == "onedir" else cli / "dist"
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--" + layout,
                "--name", "talo", "--paths", str(cli / "src"), "--collect-all", "talo",
                "--distpath", str(output), "--workpath", str(cli / "build"),
                "--specpath", str(cli / "build"), str(cli / "packaging" / "entry.py")], check=True)
binary_root = output / "talo" if layout == "onedir" else output
binary = binary_root / ("talo.exe" if sys.platform == "win32" else "talo")
metadata = {"layout": layout, "version": tomllib.loads((cli / "pyproject.toml").read_text())["project"]["version"],
            "source_sha256": hashlib.sha256(b"".join(p.relative_to(cli).as_posix().encode() + p.read_bytes() for p in sorted((cli / "src").rglob("*.py")))).hexdigest(),
            "platform": platform.platform(), "architecture": platform.machine(),
            "python_build_version": platform.python_version(), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "size_bytes": binary.stat().st_size, "release_status": "local-unpublished"}
(output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--exclude", "talo-cli"],
                        check=True, capture_output=True, text=True)
(output / "build-requirements.lock").write_text(freeze.stdout)
print(json.dumps(metadata))
