#!/usr/bin/env python3
"""
Layer 0 Pipeline — Archive Scanner
扫描原始文献目录，提取元数据，生成 Layer 0 索引。

输入: data/archive/ (原始 PDF/CHM/HTML/DJVU 文件)
输出: data/archive-index.json (文件级元数据索引)
     + knowledge/graph/relations/catalog.json (书目编目)

使用: python scripts/pipeline/layer0_extract/scan_archive.py
"""

import json
import os
import hashlib
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# 自动检测数据根目录（兼容多种放置方式）
def find_archive_dir():
    candidates = [
        PROJECT_ROOT / "data" / "_kage" / "www.marxists.org",
        PROJECT_ROOT / "data" / "www.marxists.org",
        PROJECT_ROOT / "data" / "archive",
        PROJECT_ROOT / "data" / "chinese",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            # 找到含有 PDF 文件的子目录
            for sub in c.iterdir():
                if sub.is_dir() and any(sub.glob("**/*.pdf")):
                    return c
            # 或者自身就含 pdf
            if any(c.glob("**/*.pdf")):
                return c
    return candidates[0]  # fallback

ARCHIVE_DIR = find_archive_dir()
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "data"
CATALOG_DIR = Path(__file__).parent.parent.parent.parent / "knowledge" / "graph" / "relations"

# 文件类型分类
FILE_TYPES = {
    ".pdf": "pdf",
    ".chm": "chm",
    ".html": "html",
    ".htm": "html",
    ".djvu": "djvu",
    ".txt": "text",
    ".zip": "archive",
    ".rar": "archive",
}


def scan_archive():
    """主扫描函数"""
    files = []
    stats = {"total_files": 0, "total_size_mb": 0, "by_type": {}, "by_category": {}}

    for root, dirs, filenames in os.walk(ARCHIVE_DIR):
        for fname in filenames:
            filepath = Path(root) / fname
            ext = filepath.suffix.lower()
            file_type = FILE_TYPES.get(ext, "other")

            # 跳过隐藏文件和系统文件
            if fname.startswith(".") or fname.startswith("_"):
                continue

            file_path = str(filepath.relative_to(ARCHIVE_DIR))
            size_bytes = filepath.stat().st_size
            size_mb = round(size_bytes / (1024 * 1024), 2)

            # 从路径推断分类
            parts = filepath.relative_to(ARCHIVE_DIR).parts
            category = parts[0] if len(parts) > 1 else "uncategorized"
            subcategory = parts[1] if len(parts) > 2 else ""

            stem = filepath.stem

            entry = {
                "id": f"doc://{file_path.replace(os.sep, '/')}",
                "path": file_path,
                "filename": fname,
                "extension": ext,
                "type": file_type,
                "size_bytes": size_bytes,
                "size_mb": size_mb,
                "category": category,
                "subcategory": subcategory,
                "stem": stem,
                "modified": datetime.fromtimestamp(
                    filepath.stat().st_mtime
                ).isoformat(),
            }

            files.append(entry)

            # 统计
            stats["total_files"] += 1
            stats["total_size_mb"] += size_mb
            stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

    # 排序
    files.sort(key=lambda x: x["path"])

    # 输出
    stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    result = {
        "generated_at": datetime.now().isoformat(),
        "source_dir": str(ARCHIVE_DIR),
        "stats": stats,
        "files": files,
    }

    output_path = OUTPUT_DIR / "archive-index.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 生成编目摘要
    catalog = {
        "generated_at": datetime.now().isoformat(),
        "total_documents": stats["total_files"],
        "categories": {}
    }
    for fi in files:
        cat = fi["category"]
        if cat not in catalog["categories"]:
            catalog["categories"][cat] = {"count": 0, "subcategories": {}}
        catalog["categories"][cat]["count"] += 1
        sub = fi["subcategory"]
        if sub:
            catalog["categories"][cat]["subcategories"][sub] = \
                catalog["categories"][cat]["subcategories"].get(sub, 0) + 1

    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_DIR / "catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print("=" * 50)
    print("Layer 0 Archive Scan Complete")
    print("=" * 50)
    print(f"Total files: {stats['total_files']}")
    print(f"Total size: {stats['total_size_mb']} MB")
    print(f"\nBy type:")
    for ft, count in sorted(stats["by_type"].items(), key=lambda x: -x[1]):
        print(f"  {ft:8s}: {count:4d}")
    print(f"\nTop categories:")
    for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1])[:15]:
        print(f"  {cat:30s}: {count:4d}")
    print(f"\nOutput: {output_path}")
    print(f"Catalog: {CATALOG_DIR / 'catalog.json'}")


if __name__ == "__main__":
    scan_archive()
