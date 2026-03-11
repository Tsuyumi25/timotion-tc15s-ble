"""清理原始碼，只保留 Docker 部署所需檔案

用法：配對完成、確認 docker compose up -d 正常後執行
  python3 cleanup.py
"""

import os
import shutil
from pathlib import Path

KEEP = {".env", "config.yaml", "docker-compose.yml"}

def main():
    script_dir = Path(__file__).resolve().parent
    script_name = Path(__file__).name

    # 列出將被刪除的項目
    to_delete = []
    for item in sorted(script_dir.iterdir()):
        if item.name in KEEP:
            continue
        to_delete.append(item)

    if not to_delete:
        print("沒有需要清理的檔案。")
        return

    print("將保留：")
    for name in sorted(KEEP):
        path = script_dir / name
        if path.exists():
            print(f"  ✔ {name}")
        else:
            print(f"  ⚠ {name}（不存在）")

    print(f"\n將刪除 {len(to_delete)} 個項目：")
    for item in to_delete:
        kind = "目錄" if item.is_dir() else "檔案"
        print(f"  ✘ {item.name}/") if item.is_dir() else print(f"  ✘ {item.name}")

    ans = input("\n確認？(y/N): ").strip().lower()
    if ans != "y":
        print("取消。")
        return

    for item in to_delete:
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    print("\n✔ 清理完成")
    for f in sorted(script_dir.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
