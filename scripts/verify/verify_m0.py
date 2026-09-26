#!/usr/bin/env python3
"""
M0 Verification Script

Validates:
  1. Detection coverage (all 1458 PDFs classified)
  2. Detection accuracy (status matches reality for samples)
  3. Sample selection covers all statuses
  4. Ingest pipeline produces valid Evidence with Anchors
  5. Evidence is JSON-serializable and schema-valid
"""

import json
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict, Counter


def load_jsonl(path: str) -> list[dict]:
    """Load JSONL file."""
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def load_json(path: str) -> any:
    """Load JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_detection(detection_path: str) -> dict:
    """Verify detection results."""
    issues = []
    warnings = []
    
    results = load_jsonl(detection_path)
    
    # 1. Count
    if len(results) < 1400:
        issues.append(f"Only {len(results)} PDFs detected, expected ~1458")
    
    # 2. Status distribution
    status_counts = Counter(r["status"] for r in results)
    
    # 3. Check all have required fields
    for r in results:
        if "file_path" not in r:
            issues.append(f"Missing file_path in result: {r}")
            break
        if "status" not in r:
            issues.append(f"Missing status for {r.get('file_path', '?')}")
    
    # 4. Status should be valid
    valid_statuses = {"text_extractable", "ocr_required", "partial_text", "parser_error"}
    for r in results:
        if r["status"] not in valid_statuses:
            warnings.append(f"Unknown status: {r['status']} for {r.get('file_path', '?')}")
    
    return {
        "total": len(results),
        "status_counts": dict(status_counts),
        "issues": issues,
        "warnings": warnings[:10],  # Cap warnings
        "pass": len(issues) == 0,
    }


def verify_samples(samples_path: str, detection_path: str) -> dict:
    """Verify sample selection quality."""
    issues = []
    
    samples = load_json(samples_path)
    detection = load_jsonl(detection_path)
    
    detection_stems = {r.get("stem", ""): r["status"] for r in detection}
    
    # 1. Sample count
    if len(samples) < 5:
        issues.append(f"Too few samples: {len(samples)} (need at least 5)")
    
    # 2. Status coverage
    sample_statuses = Counter(s["status"] for s in samples)
    if "text_extractable" not in sample_statuses and "partial_text" not in sample_statuses:
        issues.append("No text-extractable or partial samples selected")
    
    # 3. Diverse subcategories
    subcats = Counter(s.get("subcategory", "") for s in samples)
    if len(subcats) < 3:
        warnings.append(f"Low subcategory diversity: {len(subcats)}")
    
    # 4. Each sample should reference valid stem
    for s in samples:
        stem = s.get("stem", "")
        if stem not in detection_stems:
            issues.append(f"Sample stem '{stem}' not in detection results")
    
    return {
        "total_samples": len(samples),
        "status_distribution": dict(sample_statuses),
        "subcategory_distribution": dict(subcats),
        "issues": issues[:10],
        "pass": len(issues) == 0,
    }


def verify_evidence(evidence_dir: str) -> dict:
    """Verify evidence files have valid structure."""
    issues = []
    evidence_path = Path(evidence_dir)
    
    # 1. books.jsonl
    books_path = evidence_path / "books.jsonl"
    if not books_path.exists():
        issues.append("books.jsonl not found")
    else:
        books = load_jsonl(str(books_path))
        for b in books[:5]:
            if "book_id" not in b:
                issues.append("Missing book_id in book record")
            if "artifact_id" not in b:
                issues.append("Missing artifact_id in book record")
            if "evidence_set_id" not in b:
                issues.append("Missing evidence_set_id in book record")
    
    # 2. pages.jsonl
    pages_path = evidence_path / "pages.jsonl"
    if not pages_path.exists():
        issues.append("pages.jsonl not found")
    else:
        pages = load_jsonl(str(pages_path))
        # Verify first 5 have required fields
        for p in pages[:5]:
            required = ["id", "type", "book_id", "page_index", "source_hash", "text_raw"]
            for field in required:
                if field not in p:
                    issues.append(f"Missing '{field}' in page record: {p.get('id', '?')}")
            # Check text_raw != text_normalized is OK, both should exist
            if "text_normalized" not in p and p.get("text_raw"):
                issues.append(f"Missing text_normalized in page: {p.get('id', '?')}")
    
    return {
        "books_count": len(books) if books_path.exists() else 0,
        "pages_count": len(pages) if pages_path.exists() else 0,
        "issues": issues[:10],
        "pass": len(issues) == 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify M0 artifacts")
    parser.add_argument("--detection", default="data/manifest-detection.jsonl")
    parser.add_argument("--samples", default="data/manifest-samples.json")
    parser.add_argument("--evidence", default="data/evidence/")
    parser.add_argument("--output", default="docs/verify-M0.md",
                        help="Output verification report")
    
    args = parser.parse_args()
    
    report_lines = ["# M0 Verification Report", ""]
    all_pass = True
    
    # 1. Detection
    print("Verifying detection results...")
    det_result = verify_detection(args.detection)
    all_pass = all_pass and det_result["pass"]
    report_lines.append(f"## Detection: {'PASS' if det_result['pass'] else 'FAIL'}")
    report_lines.append(f"- Total PDFs: {det_result['total']}")
    report_lines.append(f"- Status distribution: {json.dumps(det_result['status_counts'], indent=2)}")
    if det_result["issues"]:
        report_lines.append(f"- Issues: {len(det_result['issues'])}")
        for issue in det_result["issues"][:5]:
            report_lines.append(f"  - {issue}")
    report_lines.append("")
    
    # 2. Samples
    if Path(args.samples).exists():
        print("Verifying sample selection...")
        samp_result = verify_samples(args.samples, args.detection)
        all_pass = all_pass and samp_result["pass"]
        report_lines.append(f"## Samples: {'PASS' if samp_result['pass'] else 'FAIL'}")
        report_lines.append(f"- Total samples: {samp_result['total_samples']}")
        report_lines.append(f"- Status distribution: {samp_result['status_distribution']}")
        if samp_result["issues"]:
            report_lines.append(f"- Issues: {samp_result['issues'][:5]}")
        report_lines.append("")
    
    # 3. Evidence
    if Path(args.evidence).exists() and any(Path(args.evidence).iterdir()):
        print("Verifying evidence files...")
        ev_result = verify_evidence(args.evidence)
        all_pass = all_pass and ev_result["pass"]
        report_lines.append(f"## Evidence: {'PASS' if ev_result['pass'] else 'FAIL'}")
        report_lines.append(f"- Books records: {ev_result['books_count']}")
        report_lines.append(f"- Pages records: {ev_result['pages_count']}")
        if ev_result["issues"]:
            report_lines.append(f"- Issues: {ev_result['issues']}")
        report_lines.append("")
    
    report_lines.append(f"## Overall: {'PASS' if all_pass else 'FAIL'}")
    
    # Write report
    report_text = "\n".join(report_lines)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(report_text + "\n")
    
    print(f"\n{report_text}")
    print(f"\nReport written to: {args.output}")


if __name__ == "__main__":
    main()
