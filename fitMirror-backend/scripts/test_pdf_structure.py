from pathlib import Path
import sys
from collections import defaultdict

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.rag.pdf_structured_parser import parse_pdf_structured


PDF_PATH = Path(r"C:\D\YiDong_Pan\学校\论文改进\20180210141_刘宇_论13.pdf")


def _indent(depth: int) -> str:
    return "    " * depth


def _build_tree(docs):
    """把平铺的 section_path 转成更容易阅读的树形结构。"""
    tree = {}
    for doc in docs:
        parts = [p.strip() for p in str(doc.metadata.get("section_path", "正文")).split(" > ") if p.strip()]
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
        node.setdefault("__meta__", []).append(doc.metadata)
    return tree


def _print_tree(node, depth=0):
    """递归打印章节树，只展示层级与元数据，不输出正文。"""
    for key in sorted(k for k in node.keys() if k != "__meta__"):
        metas = node[key].get("__meta__", [])
        pages = sorted({p for m in metas for p in m.get("page_range", [])})
        images = sum(len(m.get("images", [])) for m in metas)
        tables = sum(len(m.get("tables", [])) for m in metas)
        captions = sum(len(m.get("captions", [])) for m in metas)
        print(f"{_indent(depth)}- {key}  [pages={pages}, images={images}, tables={tables}, captions={captions}]")
        _print_tree(node[key], depth + 1)


def main() -> None:
    data = PDF_PATH.read_bytes()
    docs = parse_pdf_structured(data, PDF_PATH.name)

    print(f"DOC_COUNT={len(docs)}")
    print("SECTION_TREE=")
    tree = _build_tree(docs)
    _print_tree(tree)


if __name__ == "__main__":
    main()
