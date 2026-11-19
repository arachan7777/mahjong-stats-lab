#!/usr/bin/env python3
"""公開最新版SQLiteを検証後、ZIP成果物に含めるための一時書き出し。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from check_latest_db import (
    download_asset,
    extract_sqlite,
    get_release,
    validate_sqlite,
    write_reports,
    RELEASE_API,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="export")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    report = {
        "status": "失敗",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": RELEASE_API,
    }

    try:
        release = get_release()
        report["release_tag"] = release["tag_name"]
        report["release_date"] = release.get("published_at")
        matching_assets = [
            asset for asset in release.get("assets", [])
            if asset.get("name") == "database.zip"
        ]
        if len(matching_assets) != 1:
            raise RuntimeError("公開リリースにdatabase.zipが一つだけ存在しない")
        asset = matching_assets[0]
        report["asset_bytes"] = asset["size"]

        with tempfile.TemporaryDirectory(prefix="mleague-export-") as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "source_database.zip"
            sqlite_path = tmpdir / "checked.sqlite3"
            print(f"取得対象: {report['release_tag']}", flush=True)

            report["asset_sha256"] = download_asset(
                asset["browser_download_url"], asset["size"], archive
            )
            report["archive"] = extract_sqlite(archive, sqlite_path)
            report["validation"] = validate_sqlite(sqlite_path)
            print("展開したDBの整合性検査: ok", flush=True)

            exported = output / "database.sqlite3"
            if exported.exists():
                raise RuntimeError("書き出し先に同名のDBがすでに存在する")
            shutil.copyfile(sqlite_path, exported)
            report["exported_file_size"] = exported.stat().st_size
            if report["exported_file_size"] != report["archive"]["sqlite_bytes"]:
                raise RuntimeError("書き出し後のDBサイズが一致しない")
            report["exported_sqlite_sha256"] = sha256_file(exported)
            report["status"] = "成功"

        write_reports(output, report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "release": report["release_tag"],
                    "game_count": report["validation"]["counts"]["game"],
                    "kyoku_count": report["validation"]["counts"]["kyoku"],
                    "event_count": report["validation"]["counts"]["event"],
                    "last_game_date": report["validation"]["latest_game_date"],
                    "sqlite_size_bytes": report["exported_file_size"],
                    "sqlite_sha256": report["exported_sqlite_sha256"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        print(
            "検証済みDBとレポートを出力済み。GitHubにはコミットしていない。",
            flush=True,
        )
        return 0

    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr, flush=True)
        (output / "database.sqlite3").unlink(missing_ok=True)
        write_reports(output, report)
        return 1


if __name__ == "__main__":
    sys.exit(main())
