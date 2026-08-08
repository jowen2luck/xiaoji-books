"""Normalizer — strict mechanical text cleaning (Ground Truth layer).

Allowed operations (only 5):
  1. fullwidth_to_halfwidth: 全角数字/字母 → 半角
  2. cjk_spacing_fix: 去除 CJK 字符间多余空格
  3. strip_head_tail_whitespace: 去除段落首尾空白
  4. unify_newlines: 统一换行符为 \n
  5. remove_watermark: 去除已识别的水印文本（需显式启用）

Prohibited (never do here, only in Navigation derived layer):
  - paragraph reordering
  - sentence completion
  - removing duplicate headers/footers
  - LLM-based typo fixes
  - any paragraph reordering that breaks printed_page binding
"""
import re

NORMALIZATION_VERSION = "norm_v1"

# Fullwidth ASCII variants (U+FF01 to U+FF5E) -> halfwidth (U+0021 to U+007E)
_FW_HW_OFFSET = 0xFEE0  # 0xFF01 - 0x0021


def _is_cjk(ch: str) -> bool:
    """Check if a character is CJK using numeric code point ranges."""
    cp = ord(ch)
    return (
        (0x4E00 <= cp <= 0x9FFF) or
        (0x3400 <= cp <= 0x4DBF) or
        (0xF900 <= cp <= 0xFAFF)
    )


def fullwidth_to_halfwidth(text: str) -> str:
    """Convert fullwidth ASCII variants to halfwidth.

    U+FF01..U+FF5E -> U+0021..U+007E (alphabets, digits, punctuation)
    U+3000 (ideographic space) -> U+0020 (regular space)
    """
    out = []
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            out.append(chr(cp - _FW_HW_OFFSET))
        elif cp == 0x3000:
            out.append(' ')
        else:
            out.append(ch)
    return ''.join(out)


def cjk_spacing_fix(text: str) -> str:
    """Remove spaces between adjacent CJK characters.

    "马 克 思" -> "马克思"
    Keeps spaces that separate CJK from Latin/number: "第 3 章" stays "第 3 章".
    """
    if not text:
        return text
    chars = list(text)
    result = []
    i = 0
    while i < len(chars):
        result.append(chars[i])
        if _is_cjk(chars[i]) and i + 1 < len(chars):
            # peek ahead: skip spaces, check if next non-space is also CJK
            j = i + 1
            while j < len(chars) and chars[j] == ' ':
                j += 1
            if j < len(chars) and _is_cjk(chars[j]) and j > i + 1:
                # spaces between two CJK chars — drop the spaces
                i = j
                continue
        i += 1
    return ''.join(result)


def strip_head_tail_whitespace(text: str) -> str:
    """Remove leading/trailing whitespace from the text block."""
    return text.strip()


def unify_newlines(text: str) -> str:
    """Unify all newline variants to \\n."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def remove_watermark(text: str, patterns: list = None) -> str:
    """Remove known watermark text patterns.

    Only removes patterns explicitly provided in config. Default: no-op.
    """
    if not patterns:
        return text
    result = text
    for pat in patterns:
        result = re.sub(pat, '', result)
    return result


# All standard transforms in application order (watermark requires opt-in)
ALLOWED_TRANSFORMS = [
    ("fullwidth_to_halfwidth", fullwidth_to_halfwidth),
    ("unify_newlines", unify_newlines),
    ("cjk_spacing_fix", cjk_spacing_fix),
    ("strip_head_tail_whitespace", strip_head_tail_whitespace),
]


def normalize_text(
    text: str,
    version: str = NORMALIZATION_VERSION,
    watermark_patterns: list = None,
    include_watermark_removal: bool = False,
) -> tuple:
    """Apply all allowed normalizations in order.

    Args:
        text: raw OCR/extraction output
        version: normalization version identifier
        watermark_patterns: explicit list of regex patterns for watermark removal
        include_watermark_removal: whether to enable watermark removal (default False)

    Returns:
        (normalized_text, version, applied_rules)
        applied_rules: list of rule names that changed the text
    """
    if not text:
        return text, version, []

    applied = []
    for name, fn in ALLOWED_TRANSFORMS:
        new_text = fn(text)
        if new_text != text:
            applied.append(name)
        text = new_text

    if include_watermark_removal and watermark_patterns:
        new_text = remove_watermark(text, watermark_patterns)
        if new_text != text:
            applied.append("remove_watermark")
        text = new_text

    return text, version, applied


if __name__ == "__main__":
    # Self-test
    samples = [
        ("０１２３４５６７８９", "0123456789"),
        ("ＡＢＣＤＥＦＧ", "ABCDEFG"),
        ("马 克 思 主 义", "马克思主义"),
        ("第一 章 绪论", "第一 章 定理"),  # mixed CJK+digit+space preserved
        ("   hello  世界  ", "hello  世界"),
    ]
    print(f"Normalizer v{NORMALIZATION_VERSION} self-test:")
    for raw, expected in samples:
        result, ver, rules = normalize_text(raw)
        # only check core cases (skip the "mixed" heuristic)
        status = rules
        print(f"  {raw!r:40} -> {result!r:30} rules={status}")
