from __future__ import annotations
import json, re
from dataclasses import dataclass, asdict
from typing import Any
@dataclass
class JudgeScore:
    relevance: float; accuracy: float; completeness: float; usefulness: float; total: float; rationale: str=""; source: str="heuristic"
    def as_dict(self): return asdict(self)
class LLMJudge:
    def __init__(self,llm=None): self.llm=llm
    @staticmethod
    def _clamp(v):
        try:return max(0.,min(5.,float(v)))
        except:return 0.
    def _heuristic(self,q,a,context="",expected=None):
        answer=a or ""; relevance=5. if q and any(x in answer for x in q[:12]) else (3. if answer else 0.)
        completeness=5. if len(answer)>=30 else (2. if answer else 0.); usefulness=4. if answer else 0.; accuracy=4. if answer else 0.
        if expected and answer.strip()==str(expected).strip(): accuracy=5.
        total=round((relevance+accuracy+completeness+usefulness)/4,2)
        return JudgeScore(relevance,accuracy,completeness,usefulness,total,"heuristic fallback","heuristic")
    async def evaluate(self,query,answer,*,context="",expected=None):
        fallback=self._heuristic(query,answer,context,expected)
        if not self.llm:return fallback
        prompt='Return JSON only with keys relevance,accuracy,completeness,usefulness,rationale, each score 0-5.\nQuery:'+query+'\nAnswer:'+answer+'\nContext:'+context
        try:
            import asyncio
            out=await asyncio.to_thread(self.llm.invoke,prompt); raw=getattr(out,"content",out); obj=json.loads(raw if isinstance(raw,str) else str(raw))
            vals=[self._clamp(obj.get(k,0)) for k in ("relevance","accuracy","completeness","usefulness")]
            return JudgeScore(*vals,round(sum(vals)/4,2),str(obj.get("rationale","")),"llm")
        except Exception:return fallback
    async def evaluate_batch(self,samples):
        scores=[await self.evaluate(x.get("query",""),x.get("answer",""),context=x.get("context",""),expected=x.get("expected")) for x in samples]
        return {"count":len(scores),"average":round(sum(x.total for x in scores)/len(scores),2) if scores else 0,"pass_rate":sum(x.total>=3 for x in scores)/len(scores) if scores else 0,"dimensions":{k:round(sum(getattr(x,k) for x in scores)/len(scores),2) if scores else 0 for k in ("relevance","accuracy","completeness","usefulness")},"scores":[x.as_dict() for x in scores]}

