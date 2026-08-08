#!/usr/bin/env python3
"""
booklib CLI entry point

Usage:
    python -m scripts detect --help
    python -m scripts ingest --help
    python -m scripts sample --help
    python -m scripts ocr --help
"""

import sys
import os
import argparse

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(
        prog="booklib",
        description="Book Evidence & Discovery Skill CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # detect
    detect_parser = subparsers.add_parser("detect", help="Classify PDF text extractability")
    detect_parser.add_argument("--index", default="data/archive-index.json")
    detect_parser.add_argument("--source-dir", default="data/_kage/www.marxists.org")
    detect_parser.add_argument("--output", default="data/manifest-detection.jsonl")
    detect_parser.add_argument("--single", type=str, default=None)
    detect_parser.add_argument("--verbose", "-v", action="store_true")
    
    # ingest
    ingest_parser = subparsers.add_parser("ingest", help="Ingest PDFs into Evidence")
    ingest_parser.add_argument("--input", default="data/manifest-detection.jsonl")
    ingest_parser.add_argument("--output", default="data/evidence/")
    ingest_parser.add_argument("--single", type=str, default=None)
    ingest_parser.add_argument("--dry-run", action="store_true")
    
    # sample
    sample_parser = subparsers.add_parser("sample", help="Pick cross-category samples")
    sample_parser.add_argument("--input", default="data/manifest-detection.jsonl")
    sample_parser.add_argument("--output", default="data/manifest-samples.json")
    sample_parser.add_argument("--count", type=int, default=10)
    sample_parser.add_argument("--seed", type=int, default=42)
    
    # ocr
    ocr_parser = subparsers.add_parser("ocr", help="OCR pipeline for scanned PDFs")
    ocr_parser.add_argument("--pdf", required=True, help="Path to a single PDF")
    ocr_parser.add_argument("--output", default="data/evidence/ocr_smoke_output.json")
    ocr_parser.add_argument("--max-pages", type=int, default=3)
    ocr_parser.add_argument("--dpi", type=int, default=200)
    ocr_parser.add_argument("--poppler-path", default=None)

    # text-extract
    text_extract_parser = subparsers.add_parser("text-extract",
                                                help="Text extract pipeline with OCR fallback")
    text_extract_parser.add_argument("--pdf", required=True)
    text_extract_parser.add_argument("--output", default="data/evidence/text_extract_output.json")
    text_extract_parser.add_argument("--status", default="text_extractable")
    text_extract_parser.add_argument("--max-pages", type=int, default=None)
    text_extract_parser.add_argument("--dpi", type=int, default=200)
    text_extract_parser.add_argument("--no-ocr-fallback", action="store_true")
    text_extract_parser.add_argument("--poppler-path", default=None)

    # batch-ingest
    batch_parser = subparsers.add_parser("batch-ingest",
                                          help="Batch ingest all PDFs with checkpoint/resume")
    batch_parser.add_argument("--manifest", default="data/manifest.jsonl")
    batch_parser.add_argument("--base-dir", default="data/_kage/www.marxists.org")
    batch_parser.add_argument("--status-filter", default="all")
    batch_parser.add_argument("--limit", type=int, default=None)
    batch_parser.add_argument("--dpi", type=int, default=200)
    batch_parser.add_argument("--poppler-path", default=None)
    batch_parser.add_argument("--output-dir", default="data/evidence")
    batch_parser.add_argument("--checkpoint", default="data/batch_checkpoint.jsonl")
    batch_parser.add_argument("--max-pages-per-book", type=int, default=None)
    batch_parser.add_argument("--no-resume", action="store_true")
    batch_parser.add_argument("--dry-run", action="store_true")

    # catalog-load
    catalog_load_parser = subparsers.add_parser("catalog-load",
                                                 help="Load evidence JSONL into catalog.db + FTS5")
    catalog_load_parser.add_argument("--evidence-dir", default="data/evidence")
    catalog_load_parser.add_argument("--db", default="data/catalog/catalog.db")

    args = parser.parse_args()
    
    if args.command == "detect":
        from detect.detect_text import main as detect_main
        # Rebuild sys.argv for the submodule
        sys.argv = ["detect"]
        for k, v in vars(args).items():
            if k == "command":
                continue
            if v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        detect_main()
    
    elif args.command == "ingest":
        from pipeline.ingest import main as ingest_main
        sys.argv = ["ingest"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        ingest_main()
    
    elif args.command == "sample":
        from detect.sample_pick import main as sample_main
        sys.argv = ["sample"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        sample_main()

    elif args.command == "ocr":
        from pipeline.ocr_extract import main as ocr_main
        sys.argv = ["ocr"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        ocr_main()

    elif args.command == "text-extract":
        from pipeline.text_extract import main as text_extract_main
        sys.argv = ["text-extract"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        text_extract_main()

    elif args.command == "batch-ingest":
        from pipeline.batch_ingest import main as batch_ingest_main
        sys.argv = ["batch-ingest"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        batch_ingest_main()

    elif args.command == "catalog-load":
        from catalog.load_catalog import main as catalog_load_main
        sys.argv = ["catalog-load"]
        for k, v in vars(args).items():
            if k == "command" or v is None:
                continue
            if isinstance(v, bool):
                if v:
                    sys.argv.append(f"--{k}")
            else:
                sys.argv.append(f"--{k}")
                sys.argv.append(str(v))
        catalog_load_main()
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
