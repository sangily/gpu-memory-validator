"""Prepare a minimal CUDA 12.8.1 toolkit from NVIDIA's official archives."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

BASE = "https://developer.download.nvidia.com/compute/cuda/redist/"
MANIFEST = "redistrib_12.8.1.json"
COMPONENTS = ("cuda_nvcc", "cuda_cudart", "cuda_cccl", "cuda_sanitizer_api")
DEST = Path.home() / ".local/opt/cuda-12.8.1-minimal"


def main():
    if DEST.exists():
        if (DEST / "installation.json").exists():
            if not (DEST / "lib64").exists():
                (DEST / "lib64").symlink_to("lib", target_is_directory=True)
            print(f"Already prepared: {DEST}")
            return
        raise SystemExit(f"Destination exists without installation record: {DEST}")
    with urllib.request.urlopen(BASE + MANIFEST, timeout=60) as response:
        manifest_bytes = response.read()
    manifest = json.loads(manifest_bytes)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DEST.parent) as work:
        work = Path(work)
        merged = work / "toolkit"
        merged.mkdir()
        records = {}
        for name in COMPONENTS:
            entry = manifest[name]["linux-x86_64"]
            archive = work / f"{name}.tar.xz"
            url = BASE + entry["relative_path"]
            print(f"Downloading {name} ({int(entry['size']) / 1e6:.1f} MB)", flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as out:
                shutil.copyfileobj(response, out)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                raise RuntimeError(f"SHA256 mismatch: {name}")
            extracted = work / name
            extracted.mkdir()
            subprocess.run(["tar", "-xJf", str(archive), "--strip-components=1",
                            "-C", str(extracted)], check=True)
            for license_file in extracted.glob("*LICENSE*"):
                license_dest = merged / "licenses" / name
                license_dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(license_file, license_dest / license_file.name)
            shutil.copytree(extracted, merged, dirs_exist_ok=True, symlinks=True)
            records[name] = {"version": manifest[name]["version"], "url": url,
                             "sha256": digest}
        (merged / MANIFEST).write_bytes(manifest_bytes)
        # nvcc's x86_64 profile searches lib64; redistributable libraries use lib.
        (merged / "lib64").symlink_to("lib", target_is_directory=True)
        (merged / "installation.json").write_text(json.dumps(records, indent=2) + "\n")
        merged.rename(DEST)
    print(f"Prepared: {DEST}")


if __name__ == "__main__":
    main()
