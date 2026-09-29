from __future__ import annotations
import json, os, logging, hashlib
from pathlib import Path
class SkillRegistry:
    """每个 Agent 独立 JSON 技能，按 mtime 热加载；损坏文件保留上一个有效版本。"""
    def __init__(self, root=None): self.root=Path(root or os.getenv("AGENTFLOW_SKILLS_DIR", "skills")); self._cache={}; self.log=logging.getLogger(__name__)
    def load(self, agent):
        path=self.root/f"{agent}.json"
        try:
            content=path.read_bytes(); fingerprint=hashlib.sha256(content).hexdigest(); old=self._cache.get(agent)
            if old and old["fingerprint"]==fingerprint: return old["skill"]
            skill=json.loads(content.decode("utf-8-sig"));
            if not isinstance(skill,dict): raise ValueError("skill must be object")
            skill.setdefault("agent",agent); skill.setdefault("version",fingerprint[:12]); self._cache[agent]={"fingerprint":fingerprint,"skill":skill}; return skill
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
            self.log.warning("skill load failed for %s: %s", agent, exc)
            return self._cache.get(agent,{"skill":{"agent":agent,"version":"fallback","rules":[]}})["skill"]
    def inject(self,agent,prompt):
        rules=self.load(agent).get("rules",[]); return prompt+("\n\nAgent Skills:\n"+"\n".join(f"- {x}" for x in rules) if rules else "")
    def snapshot(self): return {a:self.load(a) for a in self._cache}

