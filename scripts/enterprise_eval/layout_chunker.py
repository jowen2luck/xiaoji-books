# -*- coding: utf-8 -*-
"""Enterprise Layout Parsing & Chapter-Aware Chunking Engine.

Simulates and evaluates enterprise document processing pipeline:
1. Baseline: Fixed Token Window Chunking (Sliding window, ignores layout boundaries)
2. Production: Chapter-Aware Chunking with Breadcrumb Hierarchical Paths & Table Metadata Preservation

Computes:
- Cross-Chapter Bleed Rate (CCBR)
- Metric Extraction Integrity (Table/Contract Data Preservation)
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class DocumentSection:
    section_id: str
    heading_level: int  # 1 for Chapter, 2 for Section, 3 for Subsection
    title: str
    path: str  # e.g., "第四节 财务报表 > (五) 营业收入"
    sec_type: str  # "text", "table", "title"
    content: str
    table_metadata: Optional[Dict[str, Any]] = None
    page_index: int = 0
    bbox: Optional[List[int]] = None


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    text: str
    strategy: str  # "fixed_window" or "chapter_aware"
    spanned_sections: List[str]
    is_cross_section: bool
    has_table: bool
    breadcrumb: str
    page_index: int


class EnterpriseLayoutChunker:
    """Enterprise-grade Layout Parser and Structural Chunking Engine."""

    def __init__(self, target_chunk_size: int = 500, overlap_size: int = 50):
        self.target_chunk_size = target_chunk_size
        self.overlap_size = overlap_size

    def parse_mock_enterprise_corpus(self) -> List[Dict[str, Any]]:
        """Provides representative enterprise documents (Financial Report, IT Service SLA, Legal Contract)."""
        return [
            {
                "doc_id": "CORP-FIN-2024-H1",
                "doc_title": "2024年半年度核心业务经营报告与财务附注",
                "sections": [
                    DocumentSection(
                        section_id="sec_1_1",
                        heading_level=1,
                        title="第一节 经营情况深度讨论与战略规划",
                        path="第一节 经营情况深度讨论与战略规划",
                        sec_type="text",
                        content="报告期内，公司AI智能体企业级应用商业化加速落地，在政务档案处理与跨系统知识检索场景中标多个头部标杆项目。海外业务收入占比持续爬升，整体抗风险韧性显著增强。",
                        page_index=1,
                        bbox=[50, 100, 550, 260],
                    ),
                    DocumentSection(
                        section_id="sec_2_1",
                        heading_level=2,
                        title="第二节 营业收入分部与毛利率变动",
                        path="第二节 财务数据附注 > 营业收入分部与毛利率变动",
                        sec_type="table",
                        table_metadata={
                            "table_title": "2024年上半年主营业务按行业分布构成明细",
                            "currency": "CNY (元)",
                            "audit_status": "未经审计",
                        },
                        content=(
                            "| 行业分部 | 2024年上半年收入 (元) | 2023年上半年收入 (元) | 同比增减 | 毛利率 (%) |\n"
                            "| :--- | :--- | :--- | :--- | :--- |\n"
                            "| 企业级AI基础设施 | 1,850,420,000 | 1,220,100,000 | +51.66% | 48.2% |\n"
                            "| 智能检索与知识库产品 | 920,800,000 | 640,000,000 | +43.88% | 55.4% |\n"
                            "| 传统IT集成与运维服务 | 410,200,000 | 480,500,000 | -14.63% | 18.7% |\n"
                            "| 合计 | 3,181,420,000 | 2,340,600,000 | +35.92% | 46.5% |"
                        ),
                        page_index=4,
                        bbox=[48, 120, 560, 480],
                    ),
                    DocumentSection(
                        section_id="sec_2_2",
                        heading_level=2,
                        title="第二节 财务数据附注 > 研发费用与算力租赁支出",
                        path="第二节 财务数据附注 > 研发费用与算力租赁支出",
                        sec_type="text",
                        content="2024年上半年研发开支共计4.35亿元，占当期营业总收入的13.67%。其中，GPU集群算力租赁及大模型离线训练资源消耗占比达38.5%，同比提升12.4个百分点。",
                        page_index=5,
                        bbox=[50, 80, 550, 310],
                    ),
                    DocumentSection(
                        section_id="sec_3_1",
                        heading_level=1,
                        title="第三节 重大诉讼、仲裁及或有负债",
                        path="第三节 重大诉讼、仲裁及或有负债",
                        sec_type="text",
                        content="截至本报告期末，公司及下属控股子公司不存在尚未了结的重大诉讼、仲裁事项，亦无对外提供超出法定义务范围的连带保证责任担保。",
                        page_index=12,
                        bbox=[50, 150, 550, 300],
                    ),
                ],
                "benchmark_questions": [
                    {
                        "query": "2024年上半年智能检索与知识库产品的营业收入是多少？同比增减是多少？",
                        "target_metrics": ["920,800,000", "+43.88%"],
                        "must_contain_section": "第二节 财务数据附注 > 营业收入分部与毛利率变动",
                    },
                    {
                        "query": "2024年上半年研发费用占营业收入的比例是多少？算力租赁开支占比是多少？",
                        "target_metrics": ["13.67%", "38.5%"],
                        "must_contain_section": "第二节 财务数据附注 > 研发费用与算力租赁支出",
                    },
                ],
            },
            {
                "doc_id": "CORP-SLA-2024-V2",
                "doc_title": "企业级私有云系统维护保障服务协议(SLA)",
                "sections": [
                    DocumentSection(
                        section_id="sla_1_1",
                        heading_level=1,
                        title="第一章 服务可用性等级承诺与响应时限",
                        path="第一章 服务可用性等级承诺与响应时限",
                        sec_type="text",
                        content="服务提供方承诺系统整体月度服务可用性不低于99.95%。针对P1级致命故障（生产系统核心业务完全中断），提供方应在15分钟内响应，2小时内提供应急恢复措施。",
                        page_index=2,
                        bbox=[60, 100, 540, 280],
                    ),
                    DocumentSection(
                        section_id="sla_2_1",
                        heading_level=1,
                        title="第二章 违约赔偿标准与上限责任限制",
                        path="第二章 违约赔偿标准与上限责任限制",
                        sec_type="text",
                        content="若单月可用性低于99.00%，服务提供方应按当期月度服务费的25%向客户提供服务抵扣点数；任何情形下，单季度累计赔偿总金额不超过当期季度服务费总额的50%。",
                        page_index=4,
                        bbox=[60, 120, 540, 320],
                    ),
                ],
                "benchmark_questions": [
                    {
                        "query": "P1级致命故障的响应时限与应急恢复时限要求是多长时间？",
                        "target_metrics": ["15分钟", "2小时"],
                        "must_contain_section": "第一章 服务可用性等级承诺与响应时限",
                    },
                    {
                        "query": "若系统可用性低于99%，当月赔偿比例是多少？季度赔偿上限是多少？",
                        "target_metrics": ["25%", "50%"],
                        "must_contain_section": "第二章 违约赔偿标准与上限责任限制",
                    },
                ],
            },
        ]

    def build_fixed_window_chunks(self, doc: Dict[str, Any]) -> List[ChunkRecord]:
        """Baseline Method: Flat text concatenation + sliding window."""
        doc_id = doc["doc_id"]
        sections: List[DocumentSection] = doc["sections"]

        # Concatenate into a flat stream
        flat_stream = ""
        offset_map = []
        for sec in sections:
            start_off = len(flat_stream)
            flat_stream += f"[{sec.title}]\n{sec.content}\n\n"
            end_off = len(flat_stream)
            offset_map.append((start_off, end_off, sec.path, sec.page_index, sec.sec_type == "table"))

        chunks: List[ChunkRecord] = []
        pos = 0
        chunk_idx = 0
        while pos < len(flat_stream):
            end_pos = min(pos + self.target_chunk_size, len(flat_stream))
            chunk_str = flat_stream[pos:end_pos].strip()

            if chunk_str:
                spanned = []
                has_tbl = False
                pages = []
                for s_start, s_end, s_path, p_idx, is_tbl in offset_map:
                    if max(pos, s_start) < min(end_pos, s_end):
                        spanned.append(s_path)
                        pages.append(p_idx)
                        if is_tbl:
                            has_tbl = True

                chunks.append(
                    ChunkRecord(
                        chunk_id=f"{doc_id}_fixed_{chunk_idx}",
                        doc_id=doc_id,
                        text=chunk_str,
                        strategy="fixed_window",
                        spanned_sections=spanned,
                        is_cross_section=len(spanned) > 1,
                        has_table=has_tbl,
                        breadcrumb="",
                        page_index=pages[0] if pages else 0,
                    )
                )
                chunk_idx += 1

            if end_pos >= len(flat_stream):
                break
            pos = end_pos - self.overlap_size

        return chunks

    def build_chapter_aware_chunks(self, doc: Dict[str, Any]) -> List[ChunkRecord]:
        """Enterprise Production Method: Chapter Boundary Preserved + Breadcrumbs + Table Intact."""
        doc_id = doc["doc_id"]
        doc_title = doc["doc_title"]
        sections: List[DocumentSection] = doc["sections"]
        chunks: List[ChunkRecord] = []

        for sec_idx, sec in enumerate(sections):
            breadcrumb_header = f"【文档名称】: 《{doc_title}》\n【章节层级路径】: {sec.path}\n"

            if sec.sec_type == "table":
                # Table preservation: keep Markdown table intact with table-specific metadata
                meta = sec.table_metadata or {}
                meta_line = (
                    f"【表格元数据】: 表名={meta.get('table_title', '未指定')} | "
                    f"币种={meta.get('currency', 'CNY')} | 状态={meta.get('audit_status', '已审核')}\n"
                )
                chunk_text = f"{breadcrumb_header}{meta_line}----------------------------------------\n{sec.content}"
                chunks.append(
                    ChunkRecord(
                        chunk_id=f"{doc_id}_chap_{sec_idx}_tbl",
                        doc_id=doc_id,
                        text=chunk_text,
                        strategy="chapter_aware",
                        spanned_sections=[sec.path],
                        is_cross_section=False,
                        has_table=True,
                        breadcrumb=sec.path,
                        page_index=sec.page_index,
                    )
                )
            else:
                # Text section: split internally if exceeds max chunk size, but NEVER cross section boundaries
                if len(sec.content) <= self.target_chunk_size:
                    chunk_text = f"{breadcrumb_header}----------------------------------------\n{sec.content}"
                    chunks.append(
                        ChunkRecord(
                            chunk_id=f"{doc_id}_chap_{sec_idx}_0",
                            doc_id=doc_id,
                            text=chunk_text,
                            strategy="chapter_aware",
                            spanned_sections=[sec.path],
                            is_cross_section=False,
                            has_table=False,
                            breadcrumb=sec.path,
                            page_index=sec.page_index,
                        )
                    )
                else:
                    # Inner-section sliding window
                    sub_pos = 0
                    sub_idx = 0
                    while sub_pos < len(sec.content):
                        sub_end = min(sub_pos + self.target_chunk_size, len(sec.content))
                        sub_text = sec.content[sub_pos:sub_end]
                        chunk_text = f"{breadcrumb_header}【分块分段 {sub_idx+1}】\n----------------------------------------\n{sub_text}"
                        chunks.append(
                            ChunkRecord(
                                chunk_id=f"{doc_id}_chap_{sec_idx}_{sub_idx}",
                                doc_id=doc_id,
                                text=chunk_text,
                                strategy="chapter_aware",
                                spanned_sections=[sec.path],
                                is_cross_section=False,
                                has_table=False,
                                breadcrumb=sec.path,
                                page_index=sec.page_index,
                            )
                        )
                        sub_idx += 1
                        if sub_end >= len(sec.content):
                            break
                        sub_pos = sub_end - self.overlap_size

        return chunks

    def evaluate_ablation(self) -> Dict[str, Any]:
        """Runs comparative evaluation between fixed-window and chapter-aware chunking."""
        corpus = self.parse_mock_enterprise_corpus()

        fixed_chunks_all: List[ChunkRecord] = []
        chapter_chunks_all: List[ChunkRecord] = []
        all_questions = []

        for doc in corpus:
            f_chunks = self.build_fixed_window_chunks(doc)
            c_chunks = self.build_chapter_aware_chunks(doc)
            fixed_chunks_all.extend(f_chunks)
            chapter_chunks_all.extend(c_chunks)
            for q in doc["benchmark_questions"]:
                all_questions.append((doc["doc_id"], q))

        # 1. Cross-Chapter Bleed Rate (CCBR)
        f_bleed = sum(1 for c in fixed_chunks_all if c.is_cross_section)
        c_bleed = sum(1 for c in chapter_chunks_all if c.is_cross_section)

        f_ccbr = (f_bleed / max(1, len(fixed_chunks_all))) * 100.0
        c_ccbr = (c_bleed / max(1, len(chapter_chunks_all))) * 100.0

        # 2. Metric Integrity: Does any chunk contain ALL target metrics for each QA pair?
        def calc_metric_retention(chunks: List[ChunkRecord]) -> float:
            preserved_count = 0
            for doc_id, q in all_questions:
                metrics: List[str] = q["target_metrics"]
                # A QA pair is preserved if there is AT LEAST ONE chunk that contains all required metrics
                # AND belongs to the correct section (no cross contamination)
                hit = any(
                    all(m in c.text for m in metrics) and (not c.is_cross_section)
                    for c in chunks
                    if c.doc_id == doc_id
                )
                if hit:
                    preserved_count += 1
            return (preserved_count / max(1, len(all_questions))) * 100.0

        f_retention = calc_metric_retention(fixed_chunks_all)
        c_retention = calc_metric_retention(chapter_chunks_all)

        return {
            "fixed_window": {
                "chunk_count": len(fixed_chunks_all),
                "bleed_count": f_bleed,
                "ccbr_percent": round(f_ccbr, 2),
                "metric_integrity_percent": round(f_retention, 2),
            },
            "chapter_aware": {
                "chunk_count": len(chapter_chunks_all),
                "bleed_count": c_bleed,
                "ccbr_percent": round(c_ccbr, 2),
                "metric_integrity_percent": round(c_retention, 2),
            },
            "sample_chapter_chunk": chapter_chunks_all[1].text if len(chapter_chunks_all) > 1 else "",
        }
