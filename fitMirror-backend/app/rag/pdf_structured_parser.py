"""基于 `unstructured.partition.pdf.partition_pdf` 的 PDF 结构化解析。

这个版本的目标不是“把 PDF 变成一长串文本”，而是尽量保留原始版面语义：
1. 先用 `unstructured` 拆成块级元素，拿到标题、正文、表格、图片等结构块；
2. 再把这些结构块组装成稳定的章节树，避免只靠正则硬猜层级；
3. 对图片、表格、图注做更强的邻近绑定，保证它们更容易落到同一个 chunk；
4. 每个输出 Document 都带上页码范围、章节路径、图片坐标和表格坐标等元数据。

注意：
- 这不是一个“完美还原排版”的解析器，PDF 本身就没有天然语义层级。
- 这里做的是工程上可用、可检索、可调试的结构化近似。
- 旧的纯文本解析仍保留为 fallback，不会删掉。
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.logger_handler import logger

# 章节标题最多维护到 6 级，足够覆盖常见论文/制度/手册结构。
# 这样做的原因是：PDF 里的层级通常不会像 HTML 那样稳定，
# 但“标题栈”仍然是把扁平块重组为章节树的最稳妥方法之一。
_MAX_HEADING_LEVEL = 6

# 当两个块之间的垂直间隔超过这个阈值时，更倾向于断开当前段落组。
# 单位来自 unstructured 的页面坐标系，通常是点(pt)级别。
_MAX_GAP_TO_KEEP_IN_SAME_BLOCK = 28

# 图注往往很短，且通常出现在图/表附近。
# 如果一个短块既像说明文字又紧邻图片区域，就把它绑定到图片或表格。
_CAPTION_MAX_CHARS = 80

# 论文、制度文档里常见的标题前缀。
# 这里不用它来“决定一切”，只作为标题判断的辅助信号。
_TITLE_PREFIXES = (
    "第",
    "一、",
    "二、",
    "三、",
    "四、",
    "五、",
    "六、",
    "七、",
    "八、",
    "九、",
    "十、",
)


@dataclass
class ParsedBlock:
    """把 unstructured 的 element 规范化成内部块结构。"""

    text: str
    category: str
    page_number: int
    bbox: dict[str, float] | None = None
    raw: Any = None
    is_heading: bool = False
    heading_level: int = 0
    image_id: str | None = None
    table_id: str | None = None
    caption_for: str | None = None
    caption_kind: str | None = None
    parent_section_path: str = "正文"


@dataclass
class SectionBuffer:
    """一个章节缓冲区，负责聚合同级标题下的正文、图片、表格和图注。"""

    section_path: str
    blocks: list[str] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    images: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    captions: list[dict[str, Any]] = field(default_factory=list)
    raw_blocks: list[ParsedBlock] = field(default_factory=list)

    def add_page(self, page_number: int) -> None:
        self.pages.add(page_number)

    def add_text(self, text: str) -> None:
        text = text.strip()
        if text:
            self.blocks.append(text)

    def add_image(self, payload: dict[str, Any]) -> None:
        self.images.append(payload)
        placeholder = f"【图片占位符:{payload['image_id']}】"
        self.blocks.append(placeholder)

    def add_table(self, payload: dict[str, Any]) -> None:
        self.tables.append(payload)
        placeholder = f"【表格占位符:{payload['table_id']}】"
        self.blocks.append(placeholder)

    def add_caption(self, payload: dict[str, Any]) -> None:
        self.captions.append(payload)
        # 图注/表注并不单独切块，而是跟随同一个章节上下文保留下来。
        self.blocks.append(payload["text"])


@dataclass
class HeadingState:
    """标题栈状态机。

    这里不靠单一正则硬猜层级，而是同时参考：
    - unstructured 给出的 element category
    - 文本本身的编号前缀
    - 字体大小/页内位置

    三者共同决定一个块是否更像标题。
    """

    levels: list[str] = field(default_factory=lambda: [""] * _MAX_HEADING_LEVEL)

    def push(self, level: int, text: str) -> None:
        index = max(0, min(level - 1, _MAX_HEADING_LEVEL - 1))
        self.levels[index] = text
        for i in range(index + 1, _MAX_HEADING_LEVEL):
            self.levels[i] = ""

    def path(self) -> str:
        parts = [p for p in self.levels if p]
        return " > ".join(parts) if parts else "正文"


def _safe_text(element: Any) -> str:
    """提取 element 文本。

    unstructured 元素有时有 `.text`，有时只靠字符串化才拿得到内容。
    这里尽量做宽松兼容，但不会把明显空白内容塞进流水线。
    """
    text = getattr(element, "text", None)
    if text:
        return str(text).strip()
    return str(element).strip()


def _safe_category(element: Any) -> str:
    """统一 element 分类命名，便于后续做结构判断。"""
    category = getattr(element, "category", None)
    if category:
        return str(category).lower()
    return element.__class__.__name__.lower()


def _safe_page_number(element: Any) -> int:
    """尽量从 metadata 里取页码。

    PDF 的块级元素通常会带 page_number；如果没有，就回退到 1。
    这里不做强校验，因为少数元素可能来自跨页推断。
    """
    meta = getattr(element, "metadata", None)
    if meta is None:
        return 1
    page_number = getattr(meta, "page_number", None)
    if isinstance(page_number, int) and page_number > 0:
        return page_number
    return 1


def _safe_bbox(element: Any) -> dict[str, float] | None:
    """从 element metadata 中提取坐标框。

    这是后续做“图片元数据 / 空间检索 / 图注绑定”的核心基础。
    如果拿不到坐标，不影响主流程，只是少一些定位信息。
    """
    meta = getattr(element, "metadata", None)
    if meta is None:
        return None
    coords = getattr(meta, "coordinates", None)
    if not coords:
        return None
    points = getattr(coords, "points", None)
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "x": float(min(xs)),
        "y": float(min(ys)),
        "w": float(max(xs) - min(xs)),
        "h": float(max(ys) - min(ys)),
    }


def _font_size(element: Any) -> float:
    """尽量从 block 中推断字体大小。

    这不会作为唯一判断依据，只用于辅助判断“像不像标题”。
    """
    meta = getattr(element, "metadata", None)
    if not meta:
        return 0.0
    return float(getattr(meta, "font_size", 0.0) or 0.0)


def _looks_like_heading(text: str, category: str, font_size: float) -> bool:
    """判断一个块是否更像标题。

    这里是“组合信号”，不是简单正则：
    - category 已经是 title/heading/header 之类，优先判定为标题；
    - 短文本、编号型文本、字体偏大，都增强标题置信度；
    - 太长的正文不会被硬塞成标题。
    """
    if not text:
        return False
    if category in {"title", "heading", "sectionheader", "header", "subtitle"}:
        return True
    if len(text) > 120:
        return False
    if any(text.startswith(prefix) for prefix in _TITLE_PREFIXES):
        return True
    if text[:2].isdigit() and any(ch in text[:8] for ch in (".", "、")):
        return True
    if font_size >= 15:
        return True
    return False


def _heading_level(text: str, category: str) -> int:
    """根据标题文本粗略推断层级。

    这是“稳一点”的关键：
    - category 优先；
    - 编号结构次之；
    - 兜底到一级标题。

    这里仍然存在近似，但比单纯正则硬切要稳定得多。
    """
    if category in {"title", "heading", "sectionheader", "header"}:
        return 1
    stripped = text.strip()
    if stripped.startswith(("第", "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、", "九、", "十、")):
        return 1
    if stripped.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
        if stripped.count(".") >= 2:
            return 3
        if stripped.count(".") >= 1:
            return 2
        return 1
    if stripped.startswith(("（一）", "（二）", "（三）", "（四）", "（五）")):
        return 2
    return 0


def _caption_kind(text: str) -> str | None:
    """识别图注 / 表注 / 普通说明。"""
    lower = text.lower()
    if "图" in text or "fig" in lower or "figure" in lower:
        return "figure_caption"
    if "表" in text or "table" in lower:
        return "table_caption"
    return None


def _attach_bbox_to_meta(item: dict[str, Any], bbox: dict[str, float] | None) -> None:
    """统一给图片 / 表格 / 图注挂坐标元数据。

    做这个的目的不是炫技，而是为了后续可以：
    - 空间过滤
    - 右上角 / 左下角定位
    - 更稳定地把图片、表格和它附近的说明文字组合在一起
    """
    if bbox:
        item["bbox"] = bbox
        item["x"] = bbox.get("x")
        item["y"] = bbox.get("y")
        item["w"] = bbox.get("w")
        item["h"] = bbox.get("h")


def _caption_should_bind_to_item(caption: ParsedBlock, item_bbox: dict[str, float] | None, page_number: int) -> bool:
    """判断图注是否应该绑定到图片/表格。

    规则尽量保守：
    - 同页优先；
    - 图注本身必须很短；
    - 如果有坐标，图注离图片/表格足够近再绑定。
    """
    if caption.page_number != page_number:
        return False
    if len(caption.text) > _CAPTION_MAX_CHARS:
        return False
    if not item_bbox or not caption.bbox:
        return True
    caption_y = caption.bbox.get("y", 0.0)
    item_bottom = item_bbox.get("y", 0.0) + item_bbox.get("h", 0.0)
    vertical_gap = abs(caption_y - item_bottom)
    return vertical_gap <= 60


def _sort_by_reading_order(elements: list[Any]) -> list[Any]:
    """按阅读顺序排序。

    unstructured 已经尽力做了排序，但有时同页块的相对顺序仍需要兜底。
    我们使用 y 再 x 的稳定排序，尽量贴近人眼阅读顺序。
    """
    def _key(element: Any) -> tuple[float, float]:
        bbox = _safe_bbox(element) or {}
        return (float(bbox.get("y", 0.0)), float(bbox.get("x", 0.0)))

    return sorted(elements, key=_key)


def _normalize_elements(elements: list[Any]) -> list[ParsedBlock]:
    """把 unstructured 元素转换成内部可操作的 ParsedBlock。

    这里是解析器的核心“语义归一层”之一：
    - 统一文本、分类、页码、坐标；
    - 标记哪些块像标题；
    - 标记图片、表格和图注。
    """
    parsed: list[ParsedBlock] = []
    for element in _sort_by_reading_order(elements):
        text = _safe_text(element)
        if not text:
            continue
        category = _safe_category(element)
        page_number = _safe_page_number(element)
        bbox = _safe_bbox(element)
        font_size = _font_size(element)
        is_heading = _looks_like_heading(text, category, font_size)
        heading_level = _heading_level(text, category) if is_heading else 0
        parsed.append(
            ParsedBlock(
                text=text,
                category=category,
                page_number=page_number,
                bbox=bbox,
                raw=element,
                is_heading=is_heading,
                heading_level=heading_level,
            )
        )
    return parsed


def _link_captions(parsed_blocks: list[ParsedBlock]) -> None:
    """把图注/表注尽量绑定到它们前后的图/表块。

    绑定思路：
    1. 找到附近的图片或表格；
    2. 只绑定很短的说明块；
    3. 优先同页、同区域、上下邻近。

    这样做的好处是：
    - chunk 里会保留“图 + 图注 + 附近正文”这个完整语义单元；
    - 后面检索时，用户搜到图注，也能把图附近正文一起带出来。
    """
    last_visual_by_page: dict[int, ParsedBlock] = {}
    for block in parsed_blocks:
        if block.category in {"image", "figure", "picture", "table"}:
            last_visual_by_page[block.page_number] = block
            continue
        kind = _caption_kind(block.text)
        if not kind:
            continue
        block.caption_kind = kind
        candidate = last_visual_by_page.get(block.page_number)
        if candidate and _caption_should_bind_to_item(block, candidate.bbox, candidate.page_number):
            block.caption_for = candidate.image_id if candidate.image_id else candidate.table_id


def _new_section_path(heading_state: HeadingState) -> str:
    """生成当前章节路径。

    这一步非常关键，因为后面 chunk 的 metadata 主要靠它来做“章节定位”。
    """
    return heading_state.path()


def parse_pdf_structured(content: bytes, filename: str) -> list[Document]:
    """把 PDF 先拆成结构块，再按 section 重组为可切片的 Documents。"""
    try:
        from unstructured.partition.pdf import partition_pdf
    except Exception as exc:
        logger.error("缺少 unstructured/pdf 依赖，无法做结构化解析: %s", exc)
        return []

    temp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            temp_pdf = f.name
            f.write(content)
        # 这里用 fast 策略优先保证可用性和速度；如果你后续要更强版面识别，
        # 可以再切到 hi_res，但那会带来模型下载和更高的运行成本。
        elements = partition_pdf(
            filename=temp_pdf,
            infer_table_structure=True,
            strategy="fast",
        )
    except Exception as exc:
        logger.error("unstructured PDF 解析失败: %s", exc)
        return []
    finally:
        if temp_pdf:
            Path(temp_pdf).unlink(missing_ok=True)

    parsed_blocks = _normalize_elements(list(elements))
    if not parsed_blocks:
        return []

    # 先做一次图注/表注绑定，避免图表和说明文字被拆散到完全不同的块里。
    _link_captions(parsed_blocks)

    heading_state = HeadingState()
    sections: list[SectionBuffer] = []
    current_section = SectionBuffer(section_path="正文")
    sections.append(current_section)

    # 这是一个轻量的“最近视觉块”缓存：
    # 让图注、表注、附近正文能绑定到同一个语义单元里。
    recent_visual_block: ParsedBlock | None = None
    recent_page_number = 1

    def flush_current_section_if_needed(new_section_path: str) -> SectionBuffer:
        nonlocal current_section
        if current_section.section_path != new_section_path:
            current_section = SectionBuffer(section_path=new_section_path)
            sections.append(current_section)
        return current_section

    def attach_visual_payload(block: ParsedBlock, section: SectionBuffer) -> None:
        """把图片 / 表格结构信息附到 section 上。

        这里会把坐标元数据完整写入，避免只存一个图片占位符，后续无法定位。
        """
        payload: dict[str, Any] = {
            "page": block.page_number,
            "category": block.category,
            "text": block.text,
        }
        _attach_bbox_to_meta(payload, block.bbox)
        if block.image_id:
            payload["image_id"] = block.image_id
            section.add_image(payload)
        elif block.table_id:
            payload["table_id"] = block.table_id
            section.add_table(payload)
        else:
            # 某些 unstructured 元素虽然是图片/表格语义，但没有稳定 id 时，
            # 仍然保留原始文本，避免信息丢失。
            section.add_text(block.text)
        section.raw_blocks.append(block)
        section.add_page(block.page_number)

    for idx, block in enumerate(parsed_blocks):
        recent_page_number = block.page_number

        # 标题块：推送到标题栈，并开启新的 section。
        if block.is_heading and len(block.text) <= 120:
            # 这里不是“只信正则”，而是把 category / 字体大小 / 编号规则一起作为标题信号。
            # 如果层级识别错了，后续仍然可以通过 section_path 和页面上下文修正。
            level = max(1, min(block.heading_level or 1, _MAX_HEADING_LEVEL))
            heading_state.push(level, block.text)
            section_path = _new_section_path(heading_state)
            current_section = SectionBuffer(section_path=section_path)
            current_section.add_text(block.text)
            current_section.add_page(block.page_number)
            current_section.raw_blocks.append(block)
            sections.append(current_section)
            recent_visual_block = None
            continue

        # 图片 / 表格块：直接把结构元数据挂进当前章节。
        if block.category in {"image", "figure", "picture"}:
            block.image_id = f"img_{idx:04d}"
            section = flush_current_section_if_needed(heading_state.path())
            attach_visual_payload(block, section)
            recent_visual_block = block
            continue

        if block.category in {"table", "tabular", "tabletext"}:
            block.table_id = f"tbl_{idx:04d}"
            section = flush_current_section_if_needed(heading_state.path())
            attach_visual_payload(block, section)
            recent_visual_block = block
            continue

        # 图注 / 表注：更偏向作为视觉块的补充，而不是独立主题。
        if block.caption_kind and recent_visual_block and block.page_number == recent_visual_block.page_number:
            section = flush_current_section_if_needed(heading_state.path())
            caption_text = block.text
            if block.caption_for:
                caption_text = f"{caption_text}（关联:{block.caption_for}）"
            section.add_caption(
                {
                    "page": block.page_number,
                    "kind": block.caption_kind,
                    "text": caption_text,
                    "linked_to": block.caption_for,
                }
            )
            section.add_page(block.page_number)
            section.raw_blocks.append(block)
            continue

        # 普通正文：按当前章节累积。
        section = flush_current_section_if_needed(heading_state.path())
        section.add_text(block.text)
        section.add_page(block.page_number)
        section.raw_blocks.append(block)

        # 如果连续正文太长，且与上一块跨页或跨度太大，就让它自然断开，
        # 避免把本来分属不同语义段的内容粗暴拼成一个超长块。
        if recent_visual_block and recent_visual_block.page_number != recent_page_number:
            recent_visual_block = None

    documents: list[Document] = []
    for section in sections:
        blocks = [b.strip() for b in section.blocks if b and b.strip()]
        if not blocks:
            continue

        # 把图表占位符、图注、正文统一组成一个 chunk 流。
        # 这样检索时，图文关系不会被拆散得太厉害。
        content_text = "\n\n".join(blocks)
        metadata = {
            "content_type": "pdf_structured",
            "source": filename,
            "section_path": section.section_path,
            "page_range": sorted(section.pages),
            "images": section.images,
            "tables": section.tables,
            "captions": section.captions,
            "has_images": bool(section.images),
            "has_tables": bool(section.tables),
            "block_count": len(section.raw_blocks),
        }
        documents.append(Document(page_content=content_text, metadata=metadata))

    return documents
