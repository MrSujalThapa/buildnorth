import argparse
import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

URL = "https://ndownloader.figshare.com/files/8606371"
EXPECTED_MD5 = "7412686fd77cf0e0ee1e8c3e9b354308"


def md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and verify official OULAD archive")
    parser.add_argument("--destination", type=Path, default=Path("data/oulad"))
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "anonymisedData.zip"
    if not archive.exists():
        with urllib.request.urlopen(URL) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = md5(archive)
    if actual != EXPECTED_MD5:
        raise RuntimeError(f"OULAD archive MD5 mismatch: expected {EXPECTED_MD5}, got {actual}")
    raw = destination / "raw"
    raw.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(raw)
    print(f"verified {archive} ({actual}); extracted to {raw}")


if __name__ == "__main__":
    main()
