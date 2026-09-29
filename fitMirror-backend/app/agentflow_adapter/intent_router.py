from __future__ import annotations
import asyncio, json, math, re, os
from dataclasses import dataclass
from typing import Any
from app.agentflow_adapter.schemas import IntentDecision
from app.agentflow_adapter.skills import SkillRegistry

@dataclass(frozen=True)
class _Rule:
    intent: str; group: str; agent: str; keywords: tuple[str, ...]; need_rag: bool=False; supporting: tuple[str,...]=()

class IntentRouter:
    """Pattern + embedding + LLM 融合路由，并根据 Agent 健康度动态修正候选分数。"""
    RULES=(
      _Rule("product_tryon","shopping_assistance","TryOnAgent",("试穿","上身","穿上","效果图","试试"),supporting=("ProductAdvisorAgent",)),
      _Rule("similar_product","shopping_assistance","SimilarProductAgent",("相似","同款","类似","找款"),supporting=("ProductAdvisorAgent",)),
      _Rule("product_catalog","shopping_assistance","CatalogAgent",("有哪些商品","有哪些裤子","有哪些衣服","有什么商品","现在有什么","商品列表","店里有什么","在售","推荐几件","推荐衣服","推荐裤子")),
      _Rule("product_intro","shopping_assistance","ProductAdvisorAgent",("介绍","这款","这件","商品详情","多少钱","价格","价钱","贵不贵","便宜吗","几块钱","怎么卖","售价")),
      _Rule("policy_faq","after_sales","PolicyRAGAgent",("退货","退换","退款","发货","物流","运费","保修","售后","几天到","发票","开发票","登录","登录失败","账号","支付","扣款","异常","破损","尺码","尺码表"),True),
      _Rule("product_advice","shopping_assistance","ProductAdvisorAgent",("怎么搭配","搭配","组合","适合什么风格","什么风格","适合什么")),
      _Rule("human_handoff","support","HumanHandoffAgent",("人工","客服","投诉","解决不了")),
    )
    def __init__(self, *, llm=None, embeddings=None, weights=None, timeout=4.0, monitor=None, skills=None):
        self.llm,self.embeddings,self.timeout=llm,embeddings,timeout; self.weights=weights or (.45,.35,.20); self.monitor=monitor; self.skills=skills or SkillRegistry()
        self._prototypes=[self._prototype(r) for r in self.RULES]
        # 动态规则（来自 Badcase 自动回流），权重低于静态规则，可追溯可回滚
        self._dynamic_rules: list[_Rule] = []
        self._dynamic_meta: dict[str, dict] = {}  # rule_id -> {source, badcase_id, created_at}

    def add_dynamic_rule(self, intent: str, keywords: list[str], *, source: str = "badcase_auto", badcase_id: str = "") -> str:
        """追加低权重动态规则，返回 rule_id。"""
        rule_id = f"dyn_{intent}_{abs(hash(tuple(keywords)))}"
        existing = next((r for r in self.RULES if r.intent == intent), None)
        group = existing.group if existing else "support"
        agent = existing.agent if existing else "GeneralCustomerServiceAgent"
        need_rag = existing.need_rag if existing else False
        supporting = existing.supporting if existing else ()
        rule = _Rule(intent, group, agent, tuple(keywords), need_rag=need_rag, supporting=supporting)
        self._dynamic_rules.append(rule)
        self._dynamic_meta[rule_id] = {"source": source, "badcase_id": badcase_id, "intent": intent, "keywords": keywords}
        return rule_id

    def remove_dynamic_rule(self, rule_id: str) -> bool:
        """回滚动态规则。"""
        meta = self._dynamic_meta.pop(rule_id, None)
        if not meta:
            return False
        self._dynamic_rules = [r for r in self._dynamic_rules if not (r.intent == meta["intent"] and tuple(r.keywords) == tuple(meta["keywords"]))]
        return True

    def list_dynamic_rules(self) -> list[dict]:
        return [{"rule_id": rid, **meta} for rid, meta in self._dynamic_meta.items()]

    @property
    def all_rules(self):
        return list(self.RULES) + self._dynamic_rules
    @classmethod
    def from_environment(cls):
        llm=emb=None
        if os.getenv("AGENTFLOW_INTENT_LLM_ENABLED","false").lower() in {"1","true","yes","on"}:
            try:
                from app.utils.factory import get_chat_model,get_embeddings
                llm,emb=get_chat_model(),get_embeddings()
            except Exception: pass
        try:w=tuple(float(x) for x in os.getenv("AGENTFLOW_INTENT_WEIGHTS",".45,.35,.20").split(","))
        except Exception:w=(.45,.35,.20)
        return cls(llm=llm,embeddings=emb,weights=w if len(w)==3 else None,timeout=float(os.getenv("AGENTFLOW_INTENT_TIMEOUT","4")),monitor=None,skills=SkillRegistry())
    def _prototype(self,r): return "、".join(r.keywords)
    def _pattern(self,text):
        scores=[]
        rules = self.all_rules
        dyn_count = len(self._dynamic_rules)
        for i, r in enumerate(rules):
            hits=[k for k in r.keywords if k in text]
            base = min(1.,.56+.12*len(hits)) if hits else 0.
            # 动态规则权重打 6 折，避免覆盖人工规则
            if i >= len(self.RULES):
                base *= 0.6
            scores.append((base,r,hits))
        return max(scores,key=lambda x:x[0])
    def _base(self,text,has_image=False):
        score,r,hits=self._pattern(text)
        if has_image and not hits:return self._decision("similar_product",.72,{"source":"image"})
        if not hits:return self._decision("general_chat",.45,{"source":"pattern","hits":[]})
        return self._decision(r.intent,score,{"source":"pattern","hits":hits})
    def _decision(self,intent,confidence,evidence):
        r=next((x for x in self.all_rules if x.intent==intent),None)
        return IntentDecision(primary_intent=intent,intent_group=r.group if r else "support",primary_agent=r.agent if r else "GeneralCustomerServiceAgent",supporting_agents=list(r.supporting if r else ()),confidence=max(0,min(1,confidence)),need_rag=bool(r and r.need_rag),entities={},evidence=evidence)
    def classify(self,text,*,has_image=False):
        d=self._base((text or '').strip(),has_image=has_image); m=re.search(r"(?:sku|商品|款号)[：: ]*([A-Za-z0-9_-]+)",(text or ''),re.I)
        if m:d.entities["sku_id_or_code"]=m.group(1)
        return d
    async def classify_async(self,text,*,has_image=False):
        text=(text or '').strip(); pattern=self.classify(text,has_image=has_image)
        if not self.llm and not self.embeddings:
            # Pattern-only 路径也应用 Monitor 降权，确保失败 Agent 的权重被压低
            if self.monitor:
                w = self.monitor.weight(pattern.primary_agent, 1.0)
                pattern.confidence = max(0.0, min(1.0, pattern.confidence * w))
                pattern.evidence = {**pattern.evidence, "monitor_penalty": self.monitor.penalty(pattern.primary_agent), "monitor_weight": w}
            return pattern
        p_task=asyncio.to_thread(self._embedding_scores,text) if self.embeddings else None; l_task=self._llm_score(text) if self.llm else None
        try:
            p_scores=await p_task if p_task else None
        except Exception:
            p_scores=None
        try:
            l_scores=await l_task if l_task else None
        except Exception:
            l_scores=None
        pat_score,pat_rule,_=self._pattern(text); candidates=[]
        all_rules = self.all_rules
        for i,r in enumerate(all_rules):
            pat=pat_score if r is pat_rule else (0.56 if any(k in text for k in r.keywords) else 0.0)
            # 动态规则 pattern 分打 6 折
            if i >= len(self.RULES):
                pat *= 0.6
            score=self.weights[0]*(l_scores[i] if l_scores and i < len(l_scores) else 0)+self.weights[1]*(p_scores[i] if p_scores and i < len(p_scores) else 0)+self.weights[2]*pat
            if self.monitor: score*=self.monitor.weight(r.agent,1.0)
            candidates.append(score)
        idx=max(range(len(candidates)),key=candidates.__getitem__)
        d=self._decision(all_rules[idx].intent,candidates[idx],{"source":"llm_embedding_pattern","pattern":pattern.evidence,"llm":l_scores is not None,"embedding":p_scores is not None,"weights":self.weights,"monitor_penalty":self.monitor.penalty(all_rules[idx].agent) if self.monitor else 0})
        d.entities.update(pattern.entities); return d if candidates[idx]>=.35 else pattern
    def _embedding_scores(self,text):
        all_rules = self.all_rules
        prototypes = [self._prototype(r) for r in all_rules]
        vec=self.embeddings.embed_query(text); prot=self.embeddings.embed_documents(prototypes)
        def cos(a,b):
            den=math.sqrt(sum(x*x for x in a))*math.sqrt(sum(x*x for x in b)); return sum(x*y for x,y in zip(a,b))/den if den else 0
        raw=[max(0.,cos(vec,x)) for x in prot]; mx=max(raw) if raw else 1; return [x/mx for x in raw] if mx else raw
    async def _llm_score(self,text):
        all_rules = self.all_rules
        intent_list = ','.join(r.intent for r in all_rules)
        prompt = (
            f'Classify user query into one intent: {intent_list}.\n'
            'Intent definitions:\n'
            '- product_catalog: user asks to list all products (有哪些商品/推荐几件)\n'
            '- product_intro: user asks about a specific product details, price, attributes (介绍/这款/这件/多少钱/价格)\n'
            '- product_tryon: user wants virtual try-on (试穿/穿上/效果图)\n'
            '- similar_product: user wants similar items (相似/同款/类似)\n'
            '- product_advice: user asks for styling advice (怎么搭配/适合什么风格)\n'
            '- policy_faq: user asks about returns, shipping, payment, size chart (退货/发货/尺码/支付)\n'
            '- human_handoff: user requests human agent or complains (人工/客服/投诉)\n'
            'Return JSON {"intent": "...", "confidence": 0.0-1.0}. No markdown.\n'
        )
        prompt += self.skills.inject("PolicyRAGAgent", "Routing must choose the narrowest business intent and never invent facts.")
        try:
            out = await asyncio.wait_for(asyncio.to_thread(self.llm.invoke, prompt + '\nUser:' + text), self.timeout)
            raw = getattr(out, 'content', out)
            obj = json.loads(raw if isinstance(raw, str) else str(raw))
            intent = obj.get('intent')
            return [float(obj.get('confidence', .7)) if r.intent == intent else 0.0 for r in all_rules]
        except Exception:
            return [0.0] * len(all_rules)
