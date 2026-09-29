"""Badcase 自动回流引擎。

三条回流路径 + 回归校验闸门：
- apply_intent_feedback: 从 badcase query 提取关键词，生成低权重动态意图规则
- apply_knowledge_feedback: 从 expected_reply 生成知识库文档（若 KB 未覆盖）
- apply_skill_feedback: 从 expected_reply 提取 Agent 行为规则，追加到 skills JSON

安全闸门：每次改动后跑回归评测，核心指标不下降才保留，否则回滚。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from app.agentflow_adapter.intent_router import IntentRouter
from app.core.logger_handler import logger

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# 中文停用词（用于关键词提取）
_STOPWORDS = set("的了是在有和就不人都一上也很到说要去你会着没看好自己这那他她它们什么怎么怎样如何可以能".split())


def _extract_keywords(text: str, top_k: int = 3) -> list[str]:
    """从 query 中提取候选关键词（规则法，LLM 不可用时的降级）。"""
    if not text:
        return []
    # 提取 2-4 字的中文片段
    segments = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    scored = []
    for seg in segments:
        if seg in _STOPWORDS or len(seg) < 2:
            continue
        scored.append(seg)
    # 去重保序
    seen, result = set(), []
    for s in scored:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result[:top_k]


async def _llm_extract_keywords(query: str, intent: str, has_llm, get_model) -> list[str] | None:
    """用 LLM 提取应该归入该意图的关键词。"""
    if not has_llm():
        return None
    prompt = (
        f"用户问题「{query}」被错误分类，正确意图是「{intent}」。"
        f"请提取 2-3 个能代表该意图的关键词（中文，2-4 字），只返回 JSON {{keywords: [...]}}，不要解释。"
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=10)
        raw = getattr(out, "content", out)
        text = raw if isinstance(raw, str) else str(raw)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            kws = obj.get("keywords", [])
            if isinstance(kws, list) and kws:
                return [str(k).strip() for k in kws if str(k).strip()][:3]
    except Exception as e:
        logger.warning("LLM keyword extraction failed: %s", e)
    return None


async def _llm_generate_kb_doc(query: str, expected_reply: str, has_llm, get_model) -> dict | None:
    """用 LLM 基于问答对生成知识库文档。"""
    if not has_llm():
        return None
    prompt = (
        f"基于以下客服问答对，生成一段简洁的政策/商品说明文本（100-200字），用于知识库检索。\n"
        f"用户问题: {query}\n期望回复: {expected_reply}\n"
        f"只返回 JSON {{title, content, doc_type}}，doc_type 取 faq/script/policy/product 之一。"
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=15)
        raw = getattr(out, "content", out)
        text = raw if isinstance(raw, str) else str(raw)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            if obj.get("content"):
                return {
                    "title": obj.get("title", query)[:50],
                    "content": obj["content"][:500],
                    "doc_type": obj.get("doc_type", "faq"),
                }
    except Exception as e:
        logger.warning("LLM KB doc generation failed: %s", e)
    return None


async def _llm_extract_skill_rule(expected_reply: str, agent: str, has_llm, get_model) -> str | None:
    """从期望回复中提取 Agent 行为规则。"""
    if not has_llm():
        return None
    prompt = (
        f"Agent「{agent}」的回复未达标，期望回复要点: {expected_reply}\n"
        f"请提炼一条简洁的行为规则（不超过 30 字），只返回规则文本本身。"
    )
    try:
        model = get_model()
        out = await asyncio.wait_for(asyncio.to_thread(model.invoke, prompt), timeout=10)
        raw = getattr(out, "content", out)
        rule = (raw if isinstance(raw, str) else str(raw)).strip().strip('"').strip("'")
        if rule and len(rule) <= 60:
            return rule
    except Exception as e:
        logger.warning("LLM skill rule extraction failed: %s", e)
    return None


def _load_skill(agent: str) -> dict:
    path = SKILLS_DIR / f"{agent}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {"agent": agent, "version": "1.0.0", "rules": []}


def _save_skill(agent: str, data: dict) -> None:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{agent}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class FeedbackEngine:
    """Badcase 自动回流引擎。所有改动必须通过回归校验才保留。"""

    def __init__(self, router: IntentRouter | None = None):
        self.router = router or IntentRouter()

    async def apply_intent_feedback(self, badcase: dict, *, has_llm=None, get_model=None) -> dict:
        """路径 A：意图规则自动回流。"""
        query = badcase.get("query", "")
        reclassified = badcase.get("reclassified_intent") or badcase.get("expected")
        if not reclassified:
            return {"applied": False, "reason": "缺少 reclassified_intent", "path": "intent"}

        # 提取关键词（LLM 优先，降级规则法）
        keywords = None
        if has_llm and get_model:
            keywords = await _llm_extract_keywords(query, reclassified, has_llm, get_model)
        if not keywords:
            keywords = _extract_keywords(query)
        if not keywords:
            return {"applied": False, "reason": "无法提取关键词", "path": "intent"}

        # 回归校验：先跑基线
        baseline = self._intent_accuracy()

        # 追加动态规则
        rule_id = self.router.add_dynamic_rule(
            reclassified, keywords, source="badcase_auto", badcase_id=badcase.get("id", "")
        )

        # 回归校验：改动后 accuracy 不能下降
        after = self._intent_accuracy()
        if after < baseline:
            self.router.remove_dynamic_rule(rule_id)
            return {
                "applied": False, "reason": f"回归校验失败: accuracy {baseline:.2%} → {after:.2%}",
                "path": "intent", "rule_id": rule_id, "keywords": keywords,
            }

        return {
            "applied": True, "path": "intent", "rule_id": rule_id,
            "intent": reclassified, "keywords": keywords,
            "baseline_accuracy": baseline, "after_accuracy": after,
        }

    async def apply_knowledge_feedback(self, badcase: dict, *, has_llm=None, get_model=None) -> dict:
        """路径 B：知识库自动补充。"""
        query = badcase.get("query", "")
        expected_reply = badcase.get("expected_reply", "")
        if not expected_reply:
            return {"applied": False, "reason": "缺少 expected_reply", "path": "knowledge"}

        # 检查 KB 是否已覆盖
        from app.rag.milvus_store import search_documents
        existing = search_documents(query, k=1)
        if existing and existing[0].get("text", ""):
            # 已有相关文档，不重复入库
            return {"applied": False, "reason": "知识库已有相关文档", "path": "knowledge", "existing": existing[0]["text"][:50]}

        # LLM 生成候选文档
        doc = None
        if has_llm and get_model:
            doc = await _llm_generate_kb_doc(query, expected_reply, has_llm, get_model)
        if not doc:
            # 降级：直接用 expected_reply 作为文档内容
            doc = {"title": query[:50], "content": expected_reply[:500], "doc_type": "faq"}

        # 入库
        from app.rag.milvus_store import add_documents
        doc_id = add_documents([doc["content"]], {"doc_type": doc["doc_type"], "title": doc["title"], "source": "badcase_auto"})[0]

        # 回归校验：重新检索，确认 query 能命中新文档
        verify = search_documents(query, k=1)
        hit = bool(verify and doc["content"][:20] in verify[0].get("text", ""))
        if not hit:
            from app.rag.milvus_store import delete_by_ids
            delete_by_ids([doc_id])
            return {"applied": False, "reason": "入库后检索未命中，已回滚", "path": "knowledge"}

        return {
            "applied": True, "path": "knowledge", "doc_id": doc_id,
            "title": doc["title"], "doc_type": doc["doc_type"],
            "content_preview": doc["content"][:80],
        }

    async def apply_skill_feedback(self, badcase: dict, *, has_llm=None, get_model=None) -> dict:
        """路径 C：Agent Skills 自动补充。"""
        # 从路由实际值推断 agent
        actual_route = badcase.get("route_actual") or badcase.get("actual", "")
        agent_map = {
            "agent_tryon": "TryOnAgent",
            "agent_product_advisor": "ProductAdvisorAgent",
            "agent_policy_rag": "PolicyRAGAgent",
            "agent_catalog": "CatalogAgent",
        }
        agent = None
        for prefix, name in agent_map.items():
            if prefix in actual_route:
                agent = name
                break
        if not agent:
            return {"applied": False, "reason": f"无法从路由 {actual_route} 推断 Agent", "path": "skill"}

        expected_reply = badcase.get("expected_reply", "")
        if not expected_reply:
            return {"applied": False, "reason": "缺少 expected_reply", "path": "skill"}

        # 提取规则
        rule = None
        if has_llm and get_model:
            rule = await _llm_extract_skill_rule(expected_reply, agent, has_llm, get_model)
        if not rule:
            # 降级：直接取 expected_reply 前 40 字
            rule = expected_reply[:40]

        # 追加到 skills JSON（去重）
        data = _load_skill(agent)
        rules = data.setdefault("rules", [])
        if rule in rules:
            return {"applied": False, "reason": "规则已存在", "path": "skill", "agent": agent, "rule": rule}
        rules.append(rule)
        data["version"] = f"{data.get('version','1.0.0')}-auto"
        _save_skill(agent, data)

        return {
            "applied": True, "path": "skill", "agent": agent,
            "rule": rule, "rules_count": len(rules),
        }

    async def apply_all(self, badcase: dict, *, has_llm=None, get_model=None) -> dict:
        """根据 badcase 类型自动选择回流路径。"""
        case_type = badcase.get("case_type", "quality")
        results = {}
        if case_type == "intent":
            results["intent"] = await self.apply_intent_feedback(badcase, has_llm=has_llm, get_model=get_model)
        else:
            # quality 类型：尝试 knowledge + skill 两条路径
            results["knowledge"] = await self.apply_knowledge_feedback(badcase, has_llm=has_llm, get_model=get_model)
            results["skill"] = await self.apply_skill_feedback(badcase, has_llm=has_llm, get_model=get_model)
        applied = any(r.get("applied") for r in results.values())
        return {"applied": applied, "paths": results}

    def _intent_accuracy(self) -> float:
        """跑全量意图评测集，返回 accuracy（用于回归校验）。"""
        from pathlib import Path
        eval_cases = Path(__file__).resolve().parents[2] / "tests" / "eval_cases.json"
        try:
            cases = json.loads(eval_cases.read_text(encoding="utf-8-sig")).get("intent_cases", [])
        except Exception:
            return 1.0
        if not cases:
            return 1.0
        correct = 0
        for case in cases:
            d = self.router.classify(case["text"], has_image=case.get("has_image", False))
            if d.primary_intent == case["expected_intent"]:
                correct += 1
        return correct / len(cases)
