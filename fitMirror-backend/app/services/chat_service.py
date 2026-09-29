"""AI 客服消息处理：意图路由、商品介绍、试穿、图片识别与 LangGraph 兜底."""

# routing and response contract are documented in docs/agentflow-integration.md

import asyncio
import re
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agentflow_adapter.agents.catalog_agent import CatalogAgent
from app.agentflow_adapter.agents.policy_rag_agent import PolicyRAGAgent
from app.agentflow_adapter.agents.product_advisor_agent import ProductAdvisorAgent
from app.agentflow_adapter.agents.tryon_agent import TryOnAgent
from app.agentflow_adapter.config import (
    catalog_agent_enabled,
    policy_rag_agent_enabled,
    product_advisor_agent_enabled,
    tryon_agent_enabled,
)
from app.graph.cs_graph import build_cs_graph
from app.graph.nodes.pipeline_nodes import extract_profile_from_text
from app.models.chat_history import ChatMessage, ChatSession, UserProfile
from app.models.sku import Sku
from app.services.catalog_service import build_catalog, match_image_to_sku
from app.services.similar_product_service import find_similar_product, wants_similar_match
from app.services.tryon_image_service import build_tryon_metadata, get_tryon_gallery
from app.utils.path_tool import UPLOADS_DIR, path_exists, resolve_storage_path, storage_url as path_storage_url

_cs_graph = None

DEFAULT_HEIGHT_CM = 165.0
DEFAULT_WEIGHT_KG = 55.0

WELCOME_MESSAGE = (
    "\u4eb2\u4eb2\uff0c\u6211\u5728\u54e6\uff5e\u5f53\u524d\u4eba\u5de5\u5ba2\u670d\u4e0d\u5728\u7ebf\uff0c\u6211\u662f AI \u667a\u80fd\u52a9\u624b\uff0c\u53ef\u4ee5\u5e2e\u60a8\uff1a\n"
    "\u00b7 \u5546\u54c1\u54a8\u8be2\u4e0e\u5c3a\u7801\u63a8\u8350\n"
    "\u00b7 \u53d1\u8d27\u002f\u9000\u6362\u8d27\u67e5\u8be2\n"
    "\u00b7 \u865a\u62df\u8bd5\u7a7f\u6548\u679c\u56fe\n"
    "\u00b7 \u642d\u914d\u5efa\u8bae\n"
    "\u76f4\u63a5\u8f93\u5165\u60a8\u7684\u95ee\u9898\u5c31\u53ef\u4ee5\u5566\uff5e"
)


# 常用中文字符集 + 业务相关词汇，用于评分修复结果
# 字符串按使用频率大致排序（越靠前越常用），用于 tie-break
_COMMON_CJK_STR = (
    "的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感"
    "介绍绍运运动卫衣闲简裙裤包包鞋帽上装下装外套衬衫恤价格钱尺码大小号颜色红白黑蓝绿灰紫粉黄棕吗呢吧啊呀哦啦今雨雪风火水山"
)
_COMMON_CJK = set(_COMMON_CJK_STR)
# 字符频率权重：越靠前权重越高（0~1），用于同分情况下的 tie-break
_CHAR_FREQ = {c: 1.0 - i / len(_COMMON_CJK_STR) for i, c in enumerate(_COMMON_CJK_STR)}

_NORMAL_CHARS = _COMMON_CJK | set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " ,.!;:()[]{}<>/\\-—…·\n\t"
)

# 乱码特征字符（UTF-8 字节被 GBK 解码后常见的生僻字）
_GARBLE_MARKERS = set("浠嬬粛涓€銆佸鍙堢瓑涓嬮洦鍚")

# 常见 bigram 词组，用于评分修复结果的合理性
_COMMON_BIGRAMS = {
    "介绍", "一下", "今天", "下雨", "运动", "休闲", "卫衣", "简约", "黑色",
    "吊带", "带裙", "价格", "多少", "这件", "裙子", "商品", "哪些", "什么",
    "可以", "没有", "我们", "你们", "他们", "这个", "那个", "怎么", "为什么",
    "试试", "效果", "搭配", "建议", "尺码", "合适", "喜欢", "看看", "推荐",
    "好吗", "雨吗", "对吗", "是吗", "有吗", "在吗",
    "法式", "碎花", "连衣", "衣裙", "好看", "衣服", "T恤",
    "看吗", "买吗", "要吗", "行吗", "去吗", "来吗", "吃吗",
}


def _has_garble_marker(text: str) -> bool:
    """文本中存在非常用字符（疑似乱码）时返回 True。

    不再依赖固定 marker 白名单，而是只要有字符不在 _NORMAL_CHARS 中
    （含 ?、€ 及生僻字）就尝试修复；评分机制会保证正常文本不被误改。
    """
    for c in text:
        if not _is_normal_char(c):
            return True
    return False


def _is_normal_char(c: str) -> bool:
    if c in ("?", "€"):
        return False
    return c in _NORMAL_CHARS


def _garble_score(text: str) -> float:
    """常用字占比 + 常见 bigram 数量 + 频率权重，分数越高越像正常文本。"""
    if not text:
        return 0.0
    common = sum(1 for c in text if c in _COMMON_CJK)
    bigrams = sum(1 for i in range(len(text) - 1) if text[i : i + 2] in _COMMON_BIGRAMS)
    freq = sum(_CHAR_FREQ.get(c, 0.0) for c in text) / len(text)
    return common / len(text) + bigrams * 0.5 + freq * 0.1


def _fix_garble_segment(seg: str) -> str:
    """修复一段可能是乱码的文本（GBK 解码 UTF-8 字节的逆向操作）。"""
    if not seg:
        return seg
    # € (U+20AC) 在 Windows GBK 中来自字节 0x80，手动映射回去
    seg = seg.replace("€", "\x80")
    encoded = bytearray()
    for c in seg:
        if c == "\x80":
            encoded.append(0x80)
        else:
            try:
                encoded.extend(c.encode("gbk"))
            except Exception:
                encoded.extend(c.encode("gbk", errors="replace"))
    encoded_bytes = bytes(encoded)
    seg_score = _garble_score(seg)

    def _try_decode(data: bytes) -> str | None:
        try:
            r = data.decode("utf-8")
            return r if _garble_score(r) > seg_score else None
        except Exception:
            return None

    # 1) 直接 UTF-8 解码
    r = _try_decode(encoded_bytes)
    if r is not None:
        return r

    # 2) 含 ? (0x3f) 时，每个 ? 位置独立尝试字节值（最多 2 个，65536 组合）
    q_positions = [i for i, b in enumerate(encoded_bytes) if b == 0x3F]
    if q_positions:
        best = None
        best_score = seg_score
        if len(q_positions) <= 2:
            from itertools import product
            for combo in product(range(0x00, 0x100), repeat=len(q_positions)):
                test = bytearray(encoded_bytes)
                for pos, val in zip(q_positions, combo):
                    test[pos] = val
                try:
                    result = bytes(test).decode("utf-8")
                    s = _garble_score(result)
                    if s > best_score:
                        best_score = s
                        best = result
                except Exception:
                    continue
        else:
            # 超过 2 个 ?：退化为所有 ? 替换为同一字节
            for b in range(0x00, 0x100):
                test = encoded_bytes.replace(b"?", bytes([b]))
                try:
                    result = test.decode("utf-8")
                    s = _garble_score(result)
                    if s > best_score:
                        best_score = s
                        best = result
                except Exception:
                    continue
        if best is not None:
            return best

    # 3) 尾部不完整字节（GBK 双字节被 UTF-8 截断）：去掉最后 1~2 字节再解码
    for trim in (1, 2):
        if len(encoded_bytes) > trim:
            r = _try_decode(encoded_bytes[:-trim])
            if r is not None:
                return r
    return seg


def fix_gbk_garbled(text: str) -> str:
    """修复 UTF-8 字节被 GBK 解码产生的乱码。

    用户从 GBK 编码来源（旧版 Windows 软件、终端等）复制粘贴文本时，
    UTF-8 字节可能被当作 GBK 解码，产生如「浠嬬粛涓€涓?」这类乱码。
    采用分段修复策略：只处理包含乱码特征字符的片段，保留正常文本，
    并用常用字占比 + bigram 频率做启发式评分选择最合理的解码结果。
    """
    if not text or not _has_garble_marker(text):
        return text
    result: list[str] = []
    buf: list[str] = []
    for c in text:
        if _is_normal_char(c):
            if buf:
                result.append(_fix_garble_segment("".join(buf)))
                buf = []
            result.append(c)
        else:
            buf.append(c)
    if buf:
        result.append(_fix_garble_segment("".join(buf)))
    return "".join(result)


def get_cs_graph():
    global _cs_graph
    if _cs_graph is None:
        _cs_graph = build_cs_graph()
    return _cs_graph


def sku_image_url(sku_id: str) -> str:
    return f"/api/sku/{sku_id}/image"


def storage_url(file_path: str) -> str | None:
    return path_storage_url(file_path)


def tryon_image_url(sku_id: str) -> str:
    return f"/api/sku/{sku_id}/tryon-image"


def parse_body_from_model_attrs(model_attrs: str) -> dict:
    h = w = None
    if model_attrs:
        hm = re.search(r"韬 珮\s*(\d{2,3})\s*cm", model_attrs, re.I)
        wm = re.search(r"浣撻噸\s*(\d{2,3})\s*kg", model_attrs, re.I)
        if hm:
            h = float(hm.group(1))
        if wm:
            w = float(wm.group(1))
    return {
        "height_cm": h or DEFAULT_HEIGHT_CM,
        "weight_kg": w or DEFAULT_WEIGHT_KG,
    }


def resolve_user_body(profile: UserProfile | None, sku: Sku | None = None) -> dict:
    h = profile.height_cm if profile and profile.height_cm else None
    w = profile.weight_kg if profile and profile.weight_kg else None
    defaults = parse_body_from_model_attrs(sku.model_attrs if sku else "")
    return {
        "height_cm": h or defaults["height_cm"],
        "weight_kg": w or defaults["weight_kg"],
        # is_default锛歍rue 琛ㄧず鐢ㄧ殑鏄?SKU 妯＄壒鍙傝€冭韩鏉愶紝鑰岄潪鐢ㄦ埛鑷 繁濉 殑妗ｆ 
        "is_default": not (h and w),
    }


async def find_sku_from_context(db: AsyncSession, session_id: str) -> Sku | None:
    """浠庢渶杩戜細璇濇秷鎭 腑鏌ユ壘宸茶 璁鸿繃鐨勫晢鍝侊紙鐢ㄤ簬璇曠┛绛夊悗缁 搷浣滐級銆?"""
    history = await get_history(db, session_id)
    for m in reversed(history):
        meta = m.metadata_ or {}
        sku_id = meta.get("sku_id")
        if sku_id:
            sku = await db.get(Sku, sku_id)
            if sku:
                return sku
    return None


async def invoke_cs_graph(state: dict, config: dict) -> dict:
    """Run the graph in a worker thread to avoid blocking the event loop."""
    graph = get_cs_graph()
    return await asyncio.to_thread(graph.invoke, state, config)


async def find_sku_by_text(db: AsyncSession, text: str) -> Sku | None:
    """浠庣敤鎴锋枃鏈 腑璇嗗埆鎻愬埌鐨勫晢鍝侊紙鍚嶇О/璐у彿瀛愪覆鍖归厤锛夛紝鍛戒腑鍒欒繑鍥?Sku銆?"""
    # 鎷夊彇鍏ㄥ簵鍟嗗搧鐩 綍锛沬tems 鎸?created_at 闄嶅簭锛屽厛閬嶅巻杈冩柊鐨?SKU
    catalog = await build_catalog(db)
    # 璐у彿鍖归厤鐢 細鑻辨枃璐у彿缁熶竴杞 皬鍐欙紝閬垮厤 DRESS-001 / dress-001 涓嶄竴鑷?
    text_lower = text.lower()

    for item in catalog["items"]:
        # name锛氬睍绀哄悕锛屽 銆岀 鑺辫繛琛ｈ 銆嶏紱鍛戒腑瑙勫垯涓?name in text锛堝尯鍒嗗ぇ灏忓啓锛?
        name = item.get("name") or ""
        # sku_code锛氳揣鍙凤紝濡傘€孌RESS-001銆嶏紱鍛戒腑瑙勫垯涓哄拷鐣ュぇ灏忓啓鐨勫瓙涓插尮閰?
        code = item.get("sku_code") or ""

        if name and name in text:
            # item["id"] 鏄?Sku 涓婚敭锛屽啀鏌ュ簱鎷垮畬鏁?ORM锛堝惈 model_attrs銆佸浘鐗囪矾寰勭瓑锛?
            return await db.get(Sku, item["id"])
        if code and code.lower() in text_lower:
            return await db.get(Sku, item["id"])

    # 鍚嶇О鍜岃揣鍙峰潎鏈 懡涓?
    return None


def build_product_intro_meta(sku: Sku, body: dict | None = None) -> dict:
    has_image = path_exists(sku.source_image_path)
    body = body or parse_body_from_model_attrs(sku.model_attrs)
    name = sku.name or sku.sku_code
    return {
        "type": "product_intro", "sku_id": sku.id, "sku_code": sku.sku_code,
        "name": name, "category": sku.category or "", "style": sku.style or "",
        "image_url": sku_image_url(sku.id) if has_image else None, "default_body": body,
        "actions": [
            {"type": "tryon", "label": "\u865a\u62df\u8bd5\u7a7f", "sku_id": sku.id},
            {"type": "message", "label": "\u67e5\u770b\u642d\u914d", "text": f"\u6211\u60f3\u770b\u770b{name}\u7684\u642d\u914d"},
            {"type": "message", "label": "\u5c3a\u7801\u5efa\u8bae", "text": f"\u8bf7\u7ed9\u6211{name}\u7684\u5c3a\u7801\u5efa\u8bae"},
        ],
    }


def build_product_intro_reply(sku: Sku, body: dict) -> str:
    name = sku.name or sku.sku_code
    uncategorized = "\u672a\u5206\u7c7b"
    lines = [
        f"\u4e3a\u4f60\u4ecb\u7ecd **{name}**\uff08{sku.category or uncategorized}\uff09",
        f"\u5546\u54c1\u7f16\u7801\uff1a**{sku.sku_code}**",
    ]
    if sku.style:
        lines.append(f"\u98ce\u683c\uff1a{sku.style}")
    if sku.price is not None:
        lines.append(f"\u4ef7\u683c\uff1a**\u00a5{sku.price:.2f}**")
    if sku.model_attrs:
        lines.append(f"\u5546\u54c1\u4fe1\u606f\uff1a{sku.model_attrs}")
    lines.append(f"\n\u53c2\u8003\u4f53\u578b\uff1a**{int(body['height_cm'])}cm** / **{int(body['weight_kg'])}kg**\uff0c\u9002\u5408\u6807\u51c6\u8eab\u6750\u7528\u6237\u53c2\u8003\u3002")
    lines.append("\u5982\u679c\u4f60\u544a\u8bc9\u6211\u504f\u597d\u7684\u98ce\u683c\u6216\u5c3a\u7801\uff0c\u6211\u53ef\u4ee5\u7ee7\u7eed\u7ed9\u4f60\u642d\u914d\u5efa\u8bae\u3002")
    return "\n".join(lines)


def build_similar_product_meta(sku: Sku, body: dict, *, similarity: float | None = None, reason: str = "") -> dict:
    meta = build_product_intro_meta(sku, body)
    meta["type"] = "similar_product"
    if similarity is not None:
        meta["similarity"] = round(similarity, 2)
    if reason:
        meta["match_reason"] = reason
    return meta


def build_similar_product_reply(sku: Sku, body: dict, *, user_text: str = "", reason: str = "") -> str:
    name = sku.name or sku.sku_code
    intro = f"\u4e3a\u4f60\u627e\u5230\u76f8\u4f3c\u5546\u54c1\uff1a**{name}**\u3002"
    if user_text and wants_similar_match(user_text):
        intro = f"\u6839\u636e\u4f60\u7684\u63cf\u8ff0\uff0c\u4e3a\u4f60\u63a8\u8350\uff1a**{name}**\u3002"
    lines = [intro, ""]
    if reason:
        lines.append(f"\u5339\u914d\u8bf4\u660e\uff1a{reason}")
    elif sku.style:
        lines.append(f"\u98ce\u683c\uff1a{sku.style}")
    if sku.category:
        lines.append(f"\u54c1\u7c7b\uff1a{sku.category}")
    lines.extend([f"\u5546\u54c1\u7f16\u7801\uff1a**{sku.sku_code}**", f"\n\u53c2\u8003\u4f53\u578b\uff1a**{int(body['height_cm'])}cm** / **{int(body['weight_kg'])}kg**", "\u4f60\u53ef\u4ee5\u7ee7\u7eed\u544a\u8bc9\u6211\u60f3\u770b\u7684\u98ce\u683c\uff0c\u6211\u4f1a\u5e2e\u4f60\u7b5b\u9009\u3002"])
    return "\n".join(lines)


async def create_session(db: AsyncSession, user_id: str = "guest", title: str = "\u65b0\u7684\u5bf9\u8bdd") -> ChatSession:
    session = ChatSession(id=uuid.uuid4().hex, user_id=user_id, title=title)
    db.add(session)
    await db.flush()
    await save_message(db, session.id, "assistant", WELCOME_MESSAGE)
    return session


async def list_sessions(db: AsyncSession, user_id: str = "guest") -> list[ChatSession]:
    result = await db.execute(
        select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.updated_at.desc())
    )
    return list(result.scalars().all())


def normalize_legacy_chat_text(content: str) -> str:
    """Normalize legacy display text without rewriting the original MySQL rows.

    Older frontend builds persisted a UTF-8 welcome message after decoding it as
    GBK.  We repair only strings that contain strong mojibake markers; all other
    historical content is returned unchanged.
    """
    if not content:
        return content
    if content.startswith(("\u6d5c\u8e6d\u7ff0", "\u6d5c\u8e47", "????")):
        return WELCOME_MESSAGE
    # 复用 fix_gbk_garbled 修复历史乱码（含多 ? 独立搜索与尾部截断处理）
    return fix_gbk_garbled(content)


async def get_history(db: AsyncSession, session_id: str) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    )
    return list(result.scalars().all())


async def save_message(db: AsyncSession, session_id: str, role: str, content: str, metadata: dict | None = None):
    # 入库前统一修复 GBK 乱码（用户输入与 assistant 回复均覆盖）
    content = fix_gbk_garbled(content)
    msg = ChatMessage(session_id=session_id, role=role, content=content, metadata_=metadata)
    db.add(msg)
    await db.flush()
    return msg


async def get_user_profile(db: AsyncSession, user_id: str) -> UserProfile | None:
    return await db.get(UserProfile, user_id)


async def upsert_profile(db: AsyncSession, user_id: str, height_cm: float | None, weight_kg: float | None) -> UserProfile:
    """创建或更新用户身材档案。

    使用 get-or-create 模式，并对重复键异常做容错：在高并发或事务快照隔离下，
    ``db.get`` 可能看不到已提交的行，此时 INSERT 会触发 IntegrityError，
    需要 rollback 后重新获取并更新。
    """
    from sqlalchemy.exc import IntegrityError

    try:
        profile = await db.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
        if height_cm is not None:
            profile.height_cm = height_cm
        if weight_kg is not None:
            profile.weight_kg = weight_kg
        await db.flush()
        return profile
    except IntegrityError:
        await db.rollback()
        profile = await db.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
        if height_cm is not None:
            profile.height_cm = height_cm
        if weight_kg is not None:
            profile.weight_kg = weight_kg
        await db.flush()
        return profile


async def delete_session(db: AsyncSession, session_id: str, user_id: str = "guest") -> bool:
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        return False
    await db.delete(session)
    await db.flush()
    return True


def with_executed_route(result: dict, route: str) -> dict:
    """Attach the legacy branch that actually produced a response.

    AgentFlow's ``routing`` is the recommendation; this field records the
    concrete fitMirror implementation used during the migration.
    """
    enriched = dict(result)
    enriched["executed_route"] = route
    metadata = dict(enriched.get("metadata") or {})
    metadata["executed_route"] = route
    enriched["metadata"] = metadata
    return enriched


async def introduce_product(db: AsyncSession, session_id: str, user_id: str, sku_id: str) -> dict:
    sku = await db.get(Sku, sku_id)
    if not sku:
        reply = "亲亲、未找到该商品、请从右侧商品目录重新选择哦"
        meta = {"type": "text"}
        await save_message(db, session_id, "assistant", reply, metadata=meta)
        return with_executed_route({"reply": reply, "metadata": meta}, "legacy_product_intro_not_found")

    profile = await get_user_profile(db, user_id)
    body = resolve_user_body(profile, sku)
    name = sku.name or sku.sku_code
    user_text = f"浠嬬粛涓€涓?{name}"
    await save_message(db, session_id, "user", user_text)
    reply = build_product_intro_reply(sku, body)
    meta = build_product_intro_meta(sku, parse_body_from_model_attrs(sku.model_attrs))
    await save_message(db, session_id, "assistant", reply, metadata=meta)
    return {"reply": reply, "metadata": meta}



async def process_chat_message(
    db: AsyncSession, session_id: str, user_id: str, content: str, *, skip_user_save: bool = False
) -> dict:
    """Process text chat while preserving the legacy response contract."""
    content = fix_gbk_garbled(content)
    session = await db.get(ChatSession, session_id)
    if session and session.title in ("e°的对话", "", "???"):
        session.title = content[:20] + ("..." if len(content) > 20 else "")

    if not skip_user_save:
        await save_message(db, session_id, "user", content)

    # 1. Virtual try-on: AgentFlow can take over behind a feature flag.
    tryon_kw = ("\u8bd5\u7a7f", "\u8bd5\u8bd5", "\u4e0a\u8eab", "\u6548\u679c\u56fe", "\u7a7f\u642d", "\u7a7f\u4e0a")
    if any(k in content for k in tryon_kw):
        sku = await find_sku_by_text(db, content) or await find_sku_from_context(db, session_id)
        if sku:
            if tryon_agent_enabled():
                async def tryon_provider() -> dict:
                    return await start_tryon_for_sku(
                        db, session_id, user_id, sku.id, skip_user_save=True
                    )

                try:
                    agent_response = await TryOnAgent().handle(tryon_provider)
                    metadata = dict(agent_response.artifacts[0]) if agent_response.artifacts else {
                        "type": "tryon_result"
                    }
                    metadata["agent"] = "TryOnAgent"
                    return with_executed_route(
                        {"reply": agent_response.reply, "metadata": metadata}, "agent_tryon"
                    )
                except Exception:
                    pass

            result = await start_tryon_for_sku(
                db, session_id, user_id, sku.id, skip_user_save=True
            )
            return with_executed_route(result, "legacy_tryon")

        return with_executed_route(
            {"reply": "\u4eb2\u4eb2\uff0c\u8bf7\u5148\u9009\u62e9\u4e00\u4ef6\u5546\u54c1\uff0c\u6211\u518d\u5e2e\u60a8\u8bd5\u7a7f\u54e6\u3002", "metadata": {"type": "text"}},
            "legacy_tryon_not_found",
        )

    # 2. Product introduction.
    intro_kw = ("\u4ecb\u7ecd\u4e00\u4e0b", "\u4ecb\u7ecd", "\u8be6\u60c5", "\u8fd9\u4e2a\u5546\u54c1")
    sku_in_text = await find_sku_by_text(db, content)
    wants_intro = any(k in content for k in intro_kw) and sku_in_text is not None
    if wants_intro:
        profile = await get_user_profile(db, user_id)

        async def product_advisor_provider() -> dict:
            body = resolve_user_body(profile, sku_in_text)
            return {
                "reply": build_product_intro_reply(sku_in_text, body),
                "metadata": build_product_intro_meta(sku_in_text, body),
                "intent": "product_intro",
            }

        if product_advisor_agent_enabled():
            try:
                agent_response = await ProductAdvisorAgent().handle(product_advisor_provider)
                metadata = dict(agent_response.artifacts[0]) if agent_response.artifacts else {
                    "type": "product_intro"
                }
                metadata["agent"] = "ProductAdvisorAgent"
                await save_message(db, session_id, "assistant", agent_response.reply, metadata=metadata)
                return with_executed_route(
                    {"reply": agent_response.reply, "metadata": metadata},
                    "agent_product_advisor",
                )
            except Exception:
                pass

        result = await product_advisor_provider()
        await save_message(db, session_id, "assistant", result["reply"], metadata=result["metadata"])
        return with_executed_route(
            {"reply": result["reply"], "metadata": result["metadata"]},
            "legacy_product_intro",
        )

    # 3. Catalog listing.
    browse_kw = ("\u6709\u54ea\u4e9b\u5546\u54c1", "\u6709\u4ec0\u4e48\u5546\u54c1", "\u5e97\u91cc\u6709\u4ec0\u4e48", "\u5546\u54c1\u5217\u8868", "\u5168\u90e8\u5546\u54c1")
    if any(k in content for k in browse_kw):
        if catalog_agent_enabled():
            async def catalog_provider() -> dict:
                return await build_catalog(db)

            try:
                agent_response = await CatalogAgent().handle(catalog_provider)
                catalog = agent_response.artifacts[0] if agent_response.artifacts else {}
                meta = {
                    "type": "catalog",
                    "categories": [
                        {"name": g.get("name", "未分类"), "count": g.get("count", 0)}
                        for g in catalog.get("categories", [])
                    ],
                    "agent": "CatalogAgent",
                }
                await save_message(db, session_id, "assistant", agent_response.reply, metadata=meta)
                return with_executed_route(
                    {"reply": agent_response.reply, "metadata": meta}, "agent_catalog"
                )
            except Exception:
                pass

        cat = await build_catalog(db)
        lines = [f"\u5f53\u524d\u5171\u6709 **{cat['total']}** \u4ef6\u5546\u54c1\uff1a"]
        for group in cat.get("categories", [])[:8]:
            names = "\u3001".join(item["name"] for item in group.get("items", [])[:4])
            lines.append(f"- **{group['name']}**\uff1a{group['count']} \u4ef6\uff08{names}\uff09")
        reply = "\n".join(lines)
        meta = {
            "type": "catalog",
            "categories": [
                {"name": g["name"], "count": g["count"]} for g in cat.get("categories", [])
            ],
        }
        await save_message(db, session_id, "assistant", reply, metadata=meta)
        return with_executed_route({"reply": reply, "metadata": meta}, "legacy_catalog")

    # 4. FAQ/RAG. Only business questions enter the retrieval path.
    faq_kw = ("\u9000\u6b3e", "\u9000\u8d27", "\u9000\u6362\u8d27", "\u6362\u8d27", "\u53d1\u8d27", "\u7269\u6d41", "\u5c3a\u7801", "\u652f\u4ed8", "\u53d1\u7968", "\u767b\u5f55", "\u552e\u540e")
    if any(k in content for k in faq_kw):
        from app.rag.rag_service import RagService

        async def rag_provider() -> str:
            return await RagService().aquery(content)

        if policy_rag_agent_enabled():
            try:
                agent_response = await PolicyRAGAgent().handle(rag_provider)
                if agent_response is not None:
                    meta = {"type": "faq", "agent": "PolicyRAGAgent"}
                    await save_message(db, session_id, "assistant", agent_response.reply, metadata=meta)
                    return with_executed_route(
                        {"reply": agent_response.reply, "metadata": meta}, "agent_policy_rag"
                    )
            except Exception:
                pass

        answer = await rag_provider()
        if answer:
            meta = {"type": "faq"}
            await save_message(db, session_id, "assistant", answer, metadata=meta)
            return with_executed_route(
                {"reply": answer, "metadata": meta}, "legacy_faq_rag"
            )

    # 5. General conversation remains on the existing LangGraph path.
    history = await get_history(db, session_id)
    profile = await get_user_profile(db, user_id)
    # 跨会话用户画像：从三级记忆中回忆（姓名/偏好等），注入到 LLM 上下文
    memory_profile = None
    try:
        from app.agentflow_adapter.memory_global import get_memory_manager
        mm = get_memory_manager()
        if mm:
            memory_profile = await mm.get_profile(user_id)
    except Exception:
        memory_profile = None
    messages = [
        HumanMessage(content=m.content) if m.role in ("user", "human") else AIMessage(content=m.content)
        for m in history
    ]
    state = {
        "thread_id": session_id,
        "messages": messages,
        "user_profile": {
            "height_cm": profile.height_cm if profile else None,
            "weight_kg": profile.weight_kg if profile else None,
        },
        "memory_profile": memory_profile,
    }
    result = await invoke_cs_graph(state, {"configurable": {"thread_id": session_id}})
    reply = result.get("reply_text") or "\u6211\u6682\u65f6\u6ca1\u6709\u7406\u89e3\u4f60\u7684\u95ee\u9898\uff0c\u4f60\u53ef\u4ee5\u6362\u4e00\u79cd\u65b9\u5f0f\u63cf\u8ff0\u5417\uff1f"
    if result.get("user_profile"):
        profile_data = result["user_profile"]
        # 仅当提取到身高或体重时才回写，避免无意义的 upsert 触发重复键问题
        if profile_data.get("height_cm") is not None or profile_data.get("weight_kg") is not None:
            await upsert_profile(
                db, user_id, profile_data.get("height_cm"), profile_data.get("weight_kg")
            )
    meta = {"type": "text"}
    await save_message(db, session_id, "assistant", reply, metadata=meta)
    return with_executed_route({"reply": reply, "metadata": meta}, "legacy_langgraph_chat")


async def process_combined_message(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    content: str = "",
    image_bytes: bytes | None = None,
    filename: str = "paste.png",
) -> dict:
    """Process optional image plus text, preserving image match metadata."""
    session = await db.get(ChatSession, session_id)
    text = fix_gbk_garbled((content or "").strip())
    img_url = None
    if image_bytes:
        chat_dir = UPLOADS_DIR / "chat" / session_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex[:8]}_{Path(filename).name}"
        img_path = chat_dir / safe_name
        img_path.write_bytes(image_bytes)
        img_url = f"/storage/uploads/chat/{session_id}/{safe_name}"
    if session and session.title in ("\u65b0\u7684\u5bf9\u8bdd", "", "???"):
        session.title = text[:20] if text else "\u56fe\u7247\u6d88\u606f"

    user_content = text or ("[\u56fe\u7247\u6d88\u606f]" if image_bytes else "")
    user_meta = {"type": "image", "image_url": img_url} if img_url else {}
    if text and user_meta:
        user_meta["text"] = text
    await save_message(db, session_id, "user", user_content, metadata=user_meta or None)

    if image_bytes:
        result = await match_image_to_sku(db, image_bytes)
        match = result.get("match")
        if match and not wants_similar_match(text):
            sku = await db.get(Sku, match["id"])
            if sku:
                profile = await get_user_profile(db, user_id)
                body = resolve_user_body(profile, sku)
                prefix = "\u56fe\u7247\u5339\u914d\u7ed3\u679c\uff1a" if not text else f"\u6839\u636e\u4f60\u7684\u63cf\u8ff0\u201c{text}\u201d\uff0c\u5339\u914d\u5230\uff1a"
                cat = sku.category or "\u672a\u5206\u7c7b"
                reply = (
                    f"{prefix} **{sku.name or sku.sku_code}**\uff08{cat}\uff09\n"
                    f"\u5546\u54c1\u7f16\u7801\uff1a**{sku.sku_code}**\n"
                    f"\u53c2\u8003\u4f53\u578b\uff1a**{int(body['height_cm'])}cm** / **{int(body['weight_kg'])}kg**"
                )
                meta = build_product_intro_meta(sku, body)
                meta["type"] = "product_match"
                meta["distance"] = match.get("distance")
                await save_message(db, session_id, "assistant", reply, metadata=meta)
                return with_executed_route(
                    {"reply": reply, "metadata": meta}, "legacy_image_match"
                )

        similar = await find_similar_product(db, image_bytes)
        if similar and similar.get("id"):
            sku = await db.get(Sku, similar["id"])
            if sku:
                profile = await get_user_profile(db, user_id)
                body = resolve_user_body(profile, sku)
                reason = similar.get("reason") or ""
                reply = build_similar_product_reply(sku, body, user_text=text, reason=reason)
                meta = build_similar_product_meta(
                    sku, body, similarity=similar.get("similarity"), reason=reason
                )
                if similar.get("distance") is not None:
                    meta["distance"] = similar["distance"]
                meta["match_method"] = similar.get("method")
                await save_message(db, session_id, "assistant", reply, metadata=meta)
                return with_executed_route(
                    {"reply": reply, "metadata": meta}, "legacy_similar_product"
                )

        if text:
            return await process_chat_message(db, session_id, user_id, text, skip_user_save=True)
        reply = "\u6ca1\u6709\u5339\u914d\u5230\u8be5\u56fe\u7247\u4e2d\u7684\u5546\u54c1\uff0c\u60a8\u53ef\u4ee5\u8865\u5145\u6587\u5b57\u63cf\u8ff0\u3002"
        meta = {"type": "text"}
        await save_message(db, session_id, "assistant", reply, metadata=meta)
        return with_executed_route({"reply": reply, "metadata": meta}, "legacy_image_no_match")

    return await process_chat_message(db, session_id, user_id, text, skip_user_save=True)


async def process_image_message(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    image_bytes: bytes,
    filename: str = "paste.png",
    content: str = "",
) -> dict:
    return await process_combined_message(db, session_id, user_id, content, image_bytes, filename)


async def start_tryon_for_sku(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    sku_id: str,
    *,
    skip_user_save: bool = False,
) -> dict:
    sku = await db.get(Sku, sku_id)
    if not sku:
        return with_executed_route(
            {"reply": "未找到该商品，请选择商品后再试哦～", "metadata": {"type": "text"}},
            "legacy_tryon_not_found",
        )
    profile = await get_user_profile(db, user_id)
    body = resolve_user_body(profile, sku)
    name = sku.name or sku.sku_code
    gallery = await get_tryon_gallery(db, sku_id)
    if gallery:
        body_note = "根据你的身材" if not body["is_default"] else "使用默认模特参考"
        reply = (
            f"已为 **{name}** 生成试穿效果图，{body_note}。\n"
            f"参考体型：**{int(body['height_cm'])}cm** / **{int(body['weight_kg'])}kg**"
        )
        meta = build_tryon_metadata(sku_id, name, body, gallery)
        if not skip_user_save:
            await save_message(db, session_id, "user", f"[试穿] {name}", metadata={"type": "action", "action": "tryon", "sku_id": sku_id})
        await save_message(db, session_id, "assistant", reply, metadata=meta)
        return with_executed_route({"reply": reply, "metadata": meta}, "legacy_tryon")
    reply = (
        f"亲，**{name}** 的试穿效果图正在生成中～\n"
        f"参考体型：**{int(body['height_cm'])}cm** / **{int(body['weight_kg'])}kg**\n"
        "生成完成后会自动展示，请稍候哦～"
    )
    meta = {
        "type": "tryon_result", "sku_id": sku_id, "sku_name": name,
        "image_url": None, "gallery_urls": [], "is_model_shot": False,
        "body": body, "pending_generation": True,
        "actions": [{"type": "message", "label": "查看详情", "text": f"介绍一下{name}的详情"}],
    }
    if not skip_user_save:
        await save_message(db, session_id, "user", f"[试穿] {name}", metadata={"type": "action", "action": "tryon", "sku_id": sku_id})
    await save_message(db, session_id, "assistant", reply, metadata=meta)
    return with_executed_route({"reply": reply, "metadata": meta}, "legacy_tryon")
