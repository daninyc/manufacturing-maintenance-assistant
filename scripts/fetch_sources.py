"""下载 manifest 中已核实的官方 PDF；不覆盖已有文件，记录 SHA256。"""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    raw = ROOT / "data/raw_docs"
    records = []
    for item in json.loads((raw / "manifest.json").read_text(encoding="utf-8")):
        if item["source_type"] != "manufacturer_pdf":
            continue
        path = raw / item["file"]
        if path.exists():
            content = path.read_bytes()
        else:
            with urlopen(item["source_url"], timeout=60) as response:
                content = response.read()
            if not content.startswith(b"%PDF-"):
                raise ValueError(f"下载内容不是 PDF：{item['source_url']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(content)
        records.append({"file": item["file"], "url": item["source_url"],
                        "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    output = ROOT / "docs/evidence/day2/source-downloads.json"
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
