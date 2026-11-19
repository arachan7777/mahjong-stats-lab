#!/usr/bin/env python3
"""Mリーグ公開DBの最新版を一時取得して検証する（標準ライブラリのみ）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

RELEASE_API = "https://api.github.com/repos/konoui/m-league-game-db/releases/latest"
BASELINE = {
    "game": 1932,
    "kyoku": 23550,
    "event": 2573037,
}
BASELINE_LAST_DATE = "2026-09-22"
MAX_DOWNLOAD_BYTES = 650 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024


def request(url: str):
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "mahjong-stats-lab-validator",
            "Accept": "application/vnd.github+json",
        },
    )


def get_release() -> dict:
    with urllib.request.urlopen(request(RELEASE_API), timeout=90) as response:
        return json.load(response)


def download_asset(url: str, expected_size: int, destination: Path) -> str:
    if not 0 < expected_size <= MAX_DOWNLOAD_BYTES:
        raise RuntimeError(f"配布ファイルのサイズが許容範囲外: {expected_size}")

    digest = hashlib.sha256()
    actual_size = 0
    with urllib.request.urlopen(request(url), timeout=180) as response:
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                actual_size += len(chunk)
                if actual_size > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("ダウンロード容量が上限を超過")
                digest.update(chunk)
                output.write(chunk)

    if actual_size != expected_size:
        raise RuntimeError(
            f"ダウンロードサイズが不一致: expected={expected_size}, got={actual_size}"
        )
    return digest.hexdigest()


def extract_sqlite(archive_path: Path, destination: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and (
                Path(member.filename).suffix.lower() in {".sqlite3", ".sqlite", ".db", ".db3"}
                or Path(member.filename).name.lower() in {"database", "database.sqlite"}
            )
        ]
        if not candidates:
            raise RuntimeError("ZIP内にSQLiteファイルが見つからない")

        chosen = max(candidates, key=lambda member: member.file_size)
        if not 0 < chosen.file_size <= MAX_UNCOMPRESSED_BYTES:
            raise RuntimeError("SQLiteの展開後サイズが許容範囲外")

        free_space = shutil.disk_usage(destination.parent).free
        if free_space < chosen.file_size + 512 * 1024 * 1024:
            raise RuntimeError("SQLite展開に必要な一時ディスク容量が不足")

        # ZIP内のパスは使用せず、固定の一時ファイル名へ展開する。
        with archive.open(chosen, "r") as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)

        if destination.stat().st_size != chosen.file_size:
            raise RuntimeError("展開したSQLiteのサイズが一致しない")

        return {
            "zip_member": chosen.filename,
            "sqlite_bytes": chosen.file_size,
        }


def validate_sqlite(db_path: Path) -> dict:
    db_uri = db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True, timeout=60) as connection:
        connection.execute("PRAGMA query_only=ON")
        check_rows = [row[0] for row in connection.execute("PRAGMA quick_check")]
        if check_rows != ["ok"]:
            raise RuntimeError(f"SQLite整合性検査に失敗: {check_rows[:5]}")

        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"game", "kyoku", "event"}
        missing = sorted(required - table_names)
        if missing:
            raise RuntimeError(f"必要なテーブルが不足: {missing}")

        counts = {}
        for table_name in ("game", "kyoku", "event"):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            counts[table_name] = count
            if count < BASELINE[table_name]:
                raise RuntimeError(
                    f"{table_name} の件数が旧DBより少ない: "
                    f"{count} < {BASELINE[table_name]}"
                )

        latest_date = connection.execute("SELECT MAX(date) FROM game").fetchone()[0]
        if not latest_date or str(latest_date) < BASELINE_LAST_DATE:
            raise RuntimeError(f"最終試合日が旧DBより古い: {latest_date}")

        tenpai_columns = set()
        if "player_tenpai_state" in table_names:
            tenpai_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(player_tenpai_state)"
                )
            }

        return {
            "quick_check": "ok",
            "counts": counts,
            "baseline_counts": BASELINE,
            "count_increases": {
                name: counts[name] - BASELINE[name] for name in BASELINE
            },
            "latest_game_date": str(latest_date),
            "baseline_latest_game_date": BASELINE_LAST_DATE,
            "player_tenpai_state_columns": {
                "is_actor": "is_actor" in tenpai_columns,
                "is_furiten": "is_furiten" in tenpai_columns,
            },
        }


def write_reports(output_dir: Path, report: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# MリーグDB 更新前検証レポート",
        "",
        f"- 検証結果: **{report['status']}**",
        f"- 実行日時 (UTC): {report['checked_at_utc']}",
        f"- 公開リリース: {report.get('release_tag', '取得前に失敗')}",
        f"- 公開日時: {report.get('release_date', '不明')}",
        "",
    ]
    if report.get("status") == "成功":
        data = report["validation"]
        lines += [
            "## データ確認",
            "",
            "| 項目 | 旧DB基準 | 最新DB | 増加 |",
            "|---|---:|---:|---:|",
        ]
        labels = {"game": "試合", "kyoku": "局", "event": "イベント"}
        for table in ("game", "kyoku", "event"):
            lines.append(
                f"| {labels[table]} | {BASELINE[table]:,} | "
                f"{data['counts'][table]:,} | "
                f"+{data['count_increases'][table]:,} |"
            )
        lines += [
            "",
            f"- 最終試合日: {data['latest_game_date']}",
            f"- SQLite整合性: {data['quick_check']}",
            f"- 圧縮ファイルSHA-256: {report['asset_sha256']}",
            f"- SQLite展開後サイズ: {report['archive']['sqlite_bytes']:,} bytes",
            "",
            "## 注意",
            "",
            "この検査はDBの整合性、行数、日付のみを検証する。"
            "過去の独自指標SQLとの互換性や数値一致は未検証。",
        ]
    else:
        lines += ["## エラー", "", str(report.get("error", "原因不明"))]
    (output_dir / "summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="results")
    args = parser.parse_args()
    output_dir = Path(args.output)

    report = {
        "status": "失敗",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": RELEASE_API,
    }
    try:
        release = get_release()
        report["release_tag"] = release["tag_name"]
        report["release_date"] = release.get("published_at")
        assets = [a for a in release["assets"] if a["name"] == "database.zip"]
        if len(assets) != 1:
            raise RuntimeError("公開リリースにdatabase.zipが一つだけ存在しない")
        asset = assets[0]

        print(f"対象リリース: {report['release_tag']}", flush=True)
        with tempfile.TemporaryDirectory(prefix="ml-verify-") as tmp:
            workdir = Path(tmp)
            zip_path = workdir / "database.zip"
            db_path = workdir / "latest.sqlite3"
            report["asset_bytes"] = asset["size"]
            report["asset_sha256"] = download_asset(
                asset["browser_download_url"], asset["size"], zip_path
            )
            print("ダウンロード完了・展開開始", flush=True)
            report["archive"] = extract_sqlite(zip_path, db_path)
            print("SQLite整合性・件数の検査開始", flush=True)
            report["validation"] = validate_sqlite(db_path)
            report["status"] = "成功"
        print("検証成功。DB本体は一時領域から削除済み", flush=True)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr, flush=True)
    finally:
        write_reports(output_dir, report)

    return 0 if report["status"] == "成功" else 1


if __name__ == "__main__":
    sys.exit(main())
