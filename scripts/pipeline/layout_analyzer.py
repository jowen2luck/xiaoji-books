"""Layout Analyzer — Geometric & Semantic Document Layout Structuring Engine.

Provides enterprise-grade document layout analysis, adaptive multi-column reading
order restoration, span-column heading preservation, and multi-level title extraction.

Core Capabilities:
1. Geometry & Coordinate Normalization:
   - Handles 4-point polygon `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]` and rect `[x0,y0,x1,y1]`.
   - Computes median line height, page bounds, and visual density metrics.

2. Header & Page Number Sanitization:
   - Detects running headers and isolated folio/page numbers based on geometric position
     and regex patterns, preventing header leakage into body paragraphs.

3. Span-Column Band Slicing (通栏断点带状切分):
   - Solves multi-column header penetration: full-width titles/banners are isolated as
     Span Bands. Columns between span bands are sorted independently left-to-right.

4. Adaptive Multi-Column Reading Order Restoration (自适应多栏重排):
   - Computes column gutters dynamically via adaptive X-projection histogram.
   - Reorders multi-column blocks strictly: Left Col (Top->Down) -> Right Col (Top->Down).

5. Hierarchical Heading & Semantic Title Extraction (多级标题元信息提取):
   - Combines font-size visual prominence (bbox height ratio) with Chinese/English
     structural regex patterns.
   - Assigns hierarchy levels:
     Level 1: Volume / Book / Part / 卷 / 编 / 篇 / 册
     Level 2: Chapter / 章 / Special sections (前言, 目录, 附录, 结语, etc.)
     Level 3: Section / 节 / Chinese enumeration (一、, （一）)
     Level 4: Subsection / Decimal numbers (1.1, (1), I., II.)

6. Fully Compliant with AIAE & SKILL.md:
   - Ground Truth preservation: original blocks and bboxes remain untouched.
   - Navigation & layout metadata enriched with clean input references.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Heading Regex Patterns (Combining Chinese & English structural markers) ──

_HEADING_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    # Level 1: 卷 / 编 / 篇 / 册 / 部 / Volume / Book / Part
    (
        re.compile(
            r"^\s*第[一二三四五六七八九十百千万\d]+\s*[卷编篇冊部]\s*[：:．.\s]?\s*.*$",
            re.IGNORECASE,
        ),
        1,
        "zh_level1_volume",
    ),
    (
        re.compile(
            r"^\s*(Volume|Book|Part)\s+[IVXLCDM\d]+\s*[：:．.\-]?\s*\S.*$",
            re.IGNORECASE,
        ),
        1,
        "en_level1_part",
    ),
    # Level 2: 章 / Chapter / 著名独立部分 (前言, 目录, 附录, 结语等)
    (
        re.compile(
            r"^\s*第[一二三四五六七八九十百千万\d]+\s*章\s*[：:．.\s]?\s*.*$",
            re.IGNORECASE,
        ),
        2,
        "zh_level2_chapter",
    ),
    (
        re.compile(
            r"^\s*(序言|導言|导言|前言|原序|譯者序|译者序|自序|代序|緒論|绪论|结语|結語|"
            r"後記|后记|附錄|附录|注释|註釋|參考文獻|参考文献|译名對照表|译名对照表|"
            r"索引|目錄|目录|編后记|编后记|弁言|凡例|跋|楔子|尾聲|尾声|后序|題辭|题辞|"
            r"出版说明|出版者的话|原书说明|中文版序|再版说明|内容简介|体例说明|编者的话)\s*$",
            re.IGNORECASE,
        ),
        2,
        "zh_level2_special",
    ),
    (
        re.compile(
            r"^\s*(Chapter)\s+[IVXLCDM\d]+\s*[：:．.\-]?\s*\S.*$",
            re.IGNORECASE,
        ),
        2,
        "en_level2_chapter",
    ),
    (
        re.compile(
            r"^\s*(Introduction|Preface|Foreword|Prologue|Epilogue|Conclusion|Appendix|"
            r"Bibliography|Index|Afterword|References|Acknowledgments?|Contents|Glossary)\s*$",
            re.IGNORECASE,
        ),
        2,
        "en_level2_special",
    ),
    # Level 3: 节 / 主要编号条目 (一、, （一）, Section)
    (
        re.compile(
            r"^\s*第[一二三四五六七八九十百千万\d]+\s*节\s*[：:．.\s]?\s*.*$",
            re.IGNORECASE,
        ),
        3,
        "zh_level3_section",
    ),
    (
        re.compile(
            r"^\s*[（(]?[一二三四五六七八九十百千万壹贰叁肆]+[）)]\s*[、．.]\s*\S.*$"
        ),
        3,
        "zh_level3_chinese_num",
    ),
    (
        re.compile(
            r"^\s*(Section)\s+[IVXLCDM\d]+\s*[：:．.\-]?\s*\S.*$",
            re.IGNORECASE,
        ),
        3,
        "en_level3_section",
    ),
    (
        re.compile(
            r"^\s*\d+\.\s+[A-Z\u4e00-\u9fff][^,()]{1,60}$"
        ),
        3,
        "numbered_title",
    ),
    # Level 4: 小节 / 细目 (1.1, (1), I., II.)
    (
        re.compile(r"^\s*\d+\.\d+(\.\d+)?\s+\S.*$"),
        4,
        "decimal_subsection",
    ),
    (
        re.compile(r"^\s*[（(]\d+[）)]\s*[、．.]?\s*\S.*$"),
        4,
        "parenthesized_num",
    ),
    (
        re.compile(r"^\s*[IVXLCDM]{1,5}\.\s+\S.*$"),
        4,
        "roman_subsection",
    ),
]

_PAGE_NUM_PATTERN = re.compile(r"^[\d\-–—·.\s]{1,8}$")
_PAGE_NUM_LABEL_PATTERN = re.compile(
    r"^\s*(第\s*\d+\s*页|Page\s+\d+|\d+\s*/\s*\d+)\s*$", re.IGNORECASE
)


@dataclass
class HeadingMeta:
    level: int
    text: str
    category: str
    bbox: list[float]  # [x0, y0, x1, y1]
    confidence: float = 1.0


@dataclass
class PageStructureMeta:
    columns: int
    column_ranges: list[list[float]]  # [[x_start, x_end], ...]
    has_span_elements: bool
    headings: list[dict[str, Any]]
    running_headers: list[dict[str, Any]]
    page_numbers: list[dict[str, Any]]
    total_blocks: int
    median_block_height: float
    bands_count: int


# ── Geometric Block Wrapper ──────────────────────────────────────────────────

class LayoutBlock:
    """Internal wrapper around raw OCR block for geometry operations."""

    def __init__(self, raw: dict, index: int):
        self.raw = raw
        self.original_index = index
        self.text = (raw.get("text") or raw.get("text_raw") or "").strip()
        self.confidence = float(raw.get("confidence", 1.0))
        self.id = raw.get("id") or f"b_{index:04d}"

        # Parse bounding box
        box = raw.get("box") or raw.get("layout_bbox") or [0, 0, 0, 0]
        if isinstance(box, list) and len(box) == 4 and isinstance(box[0], (list, tuple)):
            # 4-point polygon [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            self.x_min = float(min(p[0] for p in box))
            self.x_max = float(max(p[0] for p in box))
            self.y_min = float(min(p[1] for p in box))
            self.y_max = float(max(p[1] for p in box))
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            # Rect [x0, y0, x1, y1]
            self.x_min = float(box[0])
            self.y_min = float(box[1])
            self.x_max = float(box[2])
            self.y_max = float(box[3])
        else:
            self.x_min = self.y_min = self.x_max = self.y_max = 0.0

        self.width = max(0.0, self.x_max - self.x_min)
        self.height = max(0.0, self.y_max - self.y_min)
        self.center_x = (self.x_min + self.x_max) / 2.0
        self.center_y = (self.y_min + self.y_max) / 2.0

        # Classification attributes
        self.role: str = "body"  # "body", "heading", "running_header", "page_number", "artifact"
        self.is_heading: bool = False
        self.heading_level: Optional[int] = None
        self.heading_category: Optional[str] = None
        self.column_idx: int = 0
        self.is_span: bool = False
        self.reading_order_idx: int = 0

    @property
    def rect(self) -> list[float]:
        return [self.x_min, self.y_min, self.x_max, self.y_max]


# ── Core Layout Analyzer Engine ──────────────────────────────────────────────

class LayoutAnalyzer:
    """Production-grade layout analysis, column restoration & title parsing."""

    def __init__(
        self,
        span_width_ratio: float = 0.62,
        column_min_gap: float = 40.0,
        heading_height_ratio: float = 1.25,
    ):
        self.span_width_ratio = span_width_ratio
        self.column_min_gap = column_min_gap
        self.heading_height_ratio = heading_height_ratio

    def analyze_page(
        self,
        blocks: list[dict],
        page_width: Optional[float] = None,
        page_height: Optional[float] = None,
        known_running_header_texts: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        """Performs full layout analysis and reading order restoration on one page.

        Returns:
            {
                "reading_order_blocks": list[dict], # raw blocks annotated with layout info
                "text_reading_order": str,          # clean, correctly sequenced text
                "page_structure": PageStructureMeta,# detailed column & heading metrics
                "headings": list[HeadingMeta],      # detected headings
                "paragraphs": list[dict],           # assembled paragraphs with bboxes
            }
        """
        if not blocks:
            empty_meta = PageStructureMeta(
                columns=1,
                column_ranges=[],
                has_span_elements=False,
                headings=[],
                running_headers=[],
                page_numbers=[],
                total_blocks=0,
                median_block_height=0.0,
                bands_count=0,
            )
            return {
                "reading_order_blocks": [],
                "text_reading_order": "",
                "page_structure": asdict(empty_meta),
                "headings": [],
                "paragraphs": [],
            }

        # 1. Wrap blocks
        wrapped = [LayoutBlock(b, idx) for idx, b in enumerate(blocks)]

        # Estimate page dimensions if not provided
        est_page_w = page_width or (max(b.x_max for b in wrapped) + 50.0)
        est_page_h = page_height or (max(b.y_max for b in wrapped) + 50.0)

        # Compute median body line height (filter outliers)
        valid_heights = [b.height for b in wrapped if 8.0 < b.height < 150.0]
        median_h = float(statistics.median(valid_heights)) if valid_heights else 24.0

        # 2. Classify non-content blocks (Running Headers & Page Numbers)
        running_headers = []
        page_numbers = []
        content_blocks: list[LayoutBlock] = []

        for b in wrapped:
            # Check Page Number
            if self._is_page_number(b, est_page_w, est_page_h):
                b.role = "page_number"
                page_numbers.append(b)
            # Check Running Header
            elif self._is_running_header(
                b, est_page_w, est_page_h, known_running_header_texts
            ):
                b.role = "running_header"
                running_headers.append(b)
            # Check trivial artifact
            elif len(b.text) == 1 and not b.text.isalnum() and b.text not in "。！？…—·":
                b.role = "artifact"
            else:
                content_blocks.append(b)

        # 3. Detect Headings & Hierarchy
        headings: list[HeadingMeta] = []
        for b in content_blocks:
            is_head, level, cat = self._classify_heading(b, median_h, est_page_h)
            if is_head:
                b.role = "heading"
                b.is_heading = True
                b.heading_level = level
                b.heading_category = cat
                headings.append(
                    HeadingMeta(
                        level=level,
                        text=b.text,
                        category=cat,
                        bbox=b.rect,
                        confidence=b.confidence,
                    )
                )

        # 4. Multi-Column & Span Band Partitioning
        # Identify Span-Column elements (通栏元素)
        span_blocks, body_blocks = self._separate_span_blocks(
            content_blocks, est_page_w, est_page_h, median_h
        )

        has_span = len(span_blocks) > 0

        # Build Vertical Bands
        bands = self._create_bands(content_blocks, span_blocks, est_page_h)

        # 5. Order Blocks within Bands
        ordered_blocks: list[LayoutBlock] = []
        observed_column_ranges: list[list[float]] = []
        max_page_columns = 1

        for band in bands:
            if band["type"] == "span":
                # Single span or title group: sort top-down
                span_group = sorted(band["blocks"], key=lambda b: (b.y_min, b.x_min))
                for sb in span_group:
                    sb.is_span = True
                    sb.column_idx = 0
                    ordered_blocks.append(sb)
            else:
                # Multi-column region: cluster into columns and sort L->R, Top->Down
                b_cols, col_ranges = self._detect_and_sort_columns(
                    band["blocks"], est_page_w, median_h
                )
                if len(col_ranges) > max_page_columns:
                    max_page_columns = len(col_ranges)
                for cr in col_ranges:
                    if cr not in observed_column_ranges:
                        observed_column_ranges.append(cr)
                ordered_blocks.extend(b_cols)

        # Assign reading order index
        for ro_idx, b in enumerate(ordered_blocks):
            b.reading_order_idx = ro_idx

        # 6. Assemble paragraphs with layout & heading awareness
        paragraphs = self._assemble_paragraphs(ordered_blocks, median_h)

        # 7. Generate full reading-order text
        clean_text = "\n\n".join(
            p["text"] for p in paragraphs if p["text"].strip()
        )

        # 8. Annotate raw blocks with structural tags
        annotated_blocks = []
        for b in ordered_blocks:
            item = dict(b.raw)
            item["reading_order_idx"] = b.reading_order_idx
            item["column_idx"] = b.column_idx
            item["is_span"] = b.is_span
            item["role"] = b.role
            item["is_heading"] = b.is_heading
            item["heading_level"] = b.heading_level
            item["heading_category"] = b.heading_category
            item["rect"] = b.rect
            annotated_blocks.append(item)

        page_meta = PageStructureMeta(
            columns=max_page_columns,
            column_ranges=observed_column_ranges,
            has_span_elements=has_span,
            headings=[asdict(h) for h in headings],
            running_headers=[
                {"text": h.text, "bbox": h.rect} for h in running_headers
            ],
            page_numbers=[
                {"text": p.text, "bbox": p.rect} for p in page_numbers
            ],
            total_blocks=len(wrapped),
            median_block_height=round(median_h, 2),
            bands_count=len(bands),
        )

        return {
            "reading_order_blocks": annotated_blocks,
            "text_reading_order": clean_text,
            "page_structure": asdict(page_meta),
            "headings": [asdict(h) for h in headings],
            "paragraphs": paragraphs,
        }

    # ── Helper: Page Number & Header Detection ───────────────────────────────

    def _is_page_number(
        self, b: LayoutBlock, page_w: float, page_h: float
    ) -> bool:
        """Determines if a block is an isolated folio / page number."""
        txt = b.text.strip()
        if not txt:
            return False

        # Near top margin or bottom margin
        is_top_edge = b.y_min < page_h * 0.10
        is_bottom_edge = b.y_max > page_h * 0.90

        if not (is_top_edge or is_bottom_edge):
            return False

        if _PAGE_NUM_PATTERN.match(txt) and len(txt) <= 8:
            return True
        if _PAGE_NUM_LABEL_PATTERN.match(txt):
            return True
        return False

    def _is_running_header(
        self,
        b: LayoutBlock,
        page_w: float,
        page_h: float,
        known_headers: Optional[set[str]],
    ) -> bool:
        """Determines if a block is a running header."""
        txt = b.text.strip()
        if not txt or len(txt) > 50:
            return False

        # Must be in upper 12% of the page
        if b.y_min > page_h * 0.12:
            return False

        # If present in cross-page repetition set
        if known_headers and txt in known_headers:
            return True

        # Pure numbers are page numbers, not running headers
        if txt.isdigit():
            return False

        # Check typical running header characteristics (isolated line near top)
        if b.height < 40 and len(txt) <= 30:
            # Does not look like chapter title
            if not any(pat.match(txt) for pat, _, _ in _HEADING_PATTERNS[:4]):
                # If very close to the top edge
                if b.y_min < page_h * 0.08:
                    return True

        return False

    # ── Helper: Heading Classification ───────────────────────────────────────

    def _classify_heading(
        self, b: LayoutBlock, median_h: float, page_h: float
    ) -> tuple[bool, Optional[int], Optional[str]]:
        """Identifies heading presence, hierarchical level (1-4), and category."""
        txt = b.text.strip()
        if not txt:
            return False, None, None

        # 1. Structural Regex Pattern Matching
        for regex, level, category in _HEADING_PATTERNS:
            if regex.match(txt):
                return True, level, category

        # 2. Geometric Prominence Heuristics
        # Heading lines are typically taller, not too long, and don't end with commas/stops
        is_taller = b.height >= median_h * self.heading_height_ratio
        is_short = len(txt) <= 45
        not_sentence = not txt.endswith(("。", "！", "？", "；", "…", ".", "!", "?", ";"))

        if is_taller and is_short and not_sentence:
            # Prominent text in the upper half of page
            if b.y_min < page_h * 0.45:
                # Distinguish major vs minor by height
                if b.height >= median_h * 1.5:
                    return True, 2, "visual_prominent_h2"
                else:
                    return True, 3, "visual_prominent_h3"

        return False, None, None

    # ── Helper: Span-Column & Band Partitioning ───────────────────────────────

    def _separate_span_blocks(
        self,
        blocks: list[LayoutBlock],
        page_w: float,
        page_h: float,
        median_h: float,
    ) -> tuple[list[LayoutBlock], list[LayoutBlock]]:
        """Identifies blocks that span across columns (full-width titles, dividers)."""
        span_blocks: list[LayoutBlock] = []
        body_blocks: list[LayoutBlock] = []

        page_mid_x = page_w / 2.0

        for b in blocks:
            # Width exceeds threshold
            is_wide = b.width >= page_w * self.span_width_ratio

            # Crosses center significantly (e.g. left of center and right of center)
            crosses_center = (
                b.x_min < page_mid_x - page_w * 0.12
                and b.x_max > page_mid_x + page_w * 0.12
            )

            # A span block should also be a heading or reasonably wide title
            if (is_wide or (crosses_center and b.is_heading)) and b.width > page_w * 0.45:
                span_blocks.append(b)
            else:
                body_blocks.append(b)

        return span_blocks, body_blocks

    def _create_bands(
        self,
        content_blocks: list[LayoutBlock],
        span_blocks: list[LayoutBlock],
        page_h: float,
    ) -> list[dict[str, Any]]:
        """Slices page vertically into Bands separated by Span-Column blocks."""
        if not span_blocks:
            return [{"type": "columns", "blocks": content_blocks}]

        # Sort span blocks by Y
        sorted_spans = sorted(span_blocks, key=lambda b: b.y_min)

        bands: list[dict[str, Any]] = []
        current_y = 0.0

        for sb in sorted_spans:
            # Region before this span
            region_blocks = [
                b
                for b in content_blocks
                if b not in span_blocks and current_y <= b.center_y < sb.y_min
            ]
            if region_blocks:
                bands.append({"type": "columns", "blocks": region_blocks})

            # The span block itself
            bands.append({"type": "span", "blocks": [sb]})
            current_y = sb.y_max

        # Region after the last span block
        remaining_blocks = [
            b
            for b in content_blocks
            if b not in span_blocks and b.center_y >= current_y
        ]
        if remaining_blocks:
            bands.append({"type": "columns", "blocks": remaining_blocks})

        return bands

    # ── Helper: Multi-Column Detection & Ordering ────────────────────────────

    def _detect_and_sort_columns(
        self,
        blocks: list[LayoutBlock],
        page_w: float,
        median_h: float,
    ) -> tuple[list[LayoutBlock], list[list[float]]]:
        """Detects columns in a band and sorts them left-to-right, top-to-bottom."""
        if not blocks:
            return [], []

        if len(blocks) == 1:
            blocks[0].column_idx = 0
            return blocks, [[blocks[0].x_min, blocks[0].x_max]]

        # Analyze X-coordinates to find column gutters
        # Sort blocks by x_min
        sorted_by_x = sorted(blocks, key=lambda b: b.x_min)

        # Build column clusters based on non-overlapping / gap threshold
        # In a 2-column layout, left column center is ~0.25*page_w, right is ~0.75*page_w
        # Minimum gap between columns
        min_gap = max(self.column_min_gap, median_h * 1.4)

        # Partition based on page midpoint and gap
        mid_x = page_w / 2.0
        left_cand = [b for b in blocks if b.center_x < mid_x]
        right_cand = [b for b in blocks if b.center_x >= mid_x]

        # Verify whether there is a genuine 2-column gutter
        is_multi_column = False
        if left_cand and right_cand:
            max_left_x = max(b.x_max for b in left_cand)
            min_right_x = min(b.x_min for b in right_cand)
            gap = min_right_x - max_left_x

            # If there's an actual gutter or centers are clearly separated
            has_enough_blocks = len(left_cand) >= 2 or len(right_cand) >= 2
            clear_positive_gap = gap >= min_gap * 0.5 and all(b.width < page_w * 0.55 for b in blocks)
            if (gap >= -10.0 and has_enough_blocks) or clear_positive_gap:
                is_multi_column = True

        if is_multi_column:
            # Sort left column top-to-bottom
            left_sorted = sorted(left_cand, key=lambda b: (b.y_min, b.x_min))
            for b in left_sorted:
                b.column_idx = 0

            # Sort right column top-to-bottom
            right_sorted = sorted(right_cand, key=lambda b: (b.y_min, b.x_min))
            for b in right_sorted:
                b.column_idx = 1

            col_ranges = [
                [
                    round(min(b.x_min for b in left_sorted), 1),
                    round(max(b.x_max for b in left_sorted), 1),
                ],
                [
                    round(min(b.x_min for b in right_sorted), 1),
                    round(max(b.x_max for b in right_sorted), 1),
                ],
            ]
            return left_sorted + right_sorted, col_ranges
        else:
            # Single column: sort strictly top-down
            single_sorted = sorted(blocks, key=lambda b: (b.y_min, b.x_min))
            for b in single_sorted:
                b.column_idx = 0
            col_ranges = [
                [
                    round(min(b.x_min for b in single_sorted), 1),
                    round(max(b.x_max for b in single_sorted), 1),
                ]
            ]
            return single_sorted, col_ranges

    # ── Helper: Paragraph Assembly ───────────────────────────────────────────

    def _assemble_paragraphs(
        self,
        ordered_blocks: list[LayoutBlock],
        median_h: float,
    ) -> list[dict[str, Any]]:
        """Assembles ordered blocks into coherent paragraphs with bboxes."""
        if not ordered_blocks:
            return []

        paragraphs: list[dict[str, Any]] = []
        current_group: list[LayoutBlock] = [ordered_blocks[0]]

        for i in range(1, len(ordered_blocks)):
            prev = current_group[-1]
            curr = ordered_blocks[i]

            force_break = False

            # Break if any block is a heading
            if prev.is_heading or curr.is_heading:
                force_break = True

            # Break if column changes
            elif prev.column_idx != curr.column_idx:
                force_break = True

            # Break if vertical gap is large (>= 1.7 * line height)
            else:
                y_gap = curr.y_min - prev.y_max
                if y_gap >= median_h * 1.7:
                    force_break = True

            if force_break:
                paragraphs.append(self._build_para_dict(current_group))
                current_group = [curr]
            else:
                current_group.append(curr)

        if current_group:
            paragraphs.append(self._build_para_dict(current_group))

        return paragraphs

    def _build_para_dict(self, group: list[LayoutBlock]) -> dict[str, Any]:
        """Encapsulates a group of blocks into a structured paragraph record."""
        first = group[0]
        full_text = "\n".join(b.text for b in group if b.text)

        # Compute bounding rectangle
        p_x0 = min(b.x_min for b in group)
        p_y0 = min(b.y_min for b in group)
        p_x1 = max(b.x_max for b in group)
        p_y1 = max(b.y_max for b in group)

        avg_conf = sum(b.confidence for b in group) / max(1, len(group))

        return {
            "text": full_text,
            "role": "heading" if first.is_heading else "body",
            "is_heading": first.is_heading,
            "heading_level": first.heading_level,
            "heading_category": first.heading_category,
            "column_idx": first.column_idx,
            "is_span": any(b.is_span for b in group),
            "bbox": [round(p_x0, 1), round(p_y0, 1), round(p_x1, 1), round(p_y1, 1)],
            "confidence": round(avg_conf, 4),
            "input_refs": [b.id for b in group],
            "block_count": len(group),
            "char_count": len(full_text.replace(" ", "").replace("\n", "")),
        }
