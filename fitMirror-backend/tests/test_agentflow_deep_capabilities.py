import asyncio, json, tempfile, time
from pathlib import Path
from app.agentflow_adapter.memory import MemoryManager
from app.agentflow_adapter.skills import SkillRegistry
from app.agentflow_adapter.monitor import AgentHealthMonitor
from app.agentflow_adapter.judge import LLMJudge
from app.agentflow_adapter.distributed_gateway import DistributedToolGateway
from app.agentflow_adapter.intent_router import IntentRouter

async def test_memory_local_tiers_and_truncation():
 m=MemoryManager(max_working_turns=2)
 for i in range(3): await m.append_turn('s','user',str(i),user_id='u')
 assert [x['content'] for x in await m.get_working('s')]==['1','2']
 await m.save_summary('s','likes blue',user_id='u')
 r=await m.recall('u','s','blue'); assert len(r['working'])==2 and r['summaries'][0]['summary']=='likes blue' and r['profiles']==[]
 try: await m.save_profile('u','private profile')
 except NotImplementedError: pass
 else: raise AssertionError('profile storage must remain disabled until isolated storage exists')
async def test_memory_fake_redis():
 class R:
  def __init__(self): self.d={}
  async def rpush(self,k,v): self.d.setdefault(k,[]).append(v)
  async def ltrim(self,k,a,b): self.d[k]=self.d[k][a:]
  async def lrange(self,k,a,b): return self.d.get(k,[])
  async def set(self,k,v,ex=None): self.d[k]=v
  async def get(self,k): return self.d.get(k)
 r=R(); m=MemoryManager(redis_client=r); await m.append_turn('s','user','hi',user_id='u'); await m.save_summary('s','sum',user_id='u'); got=await m.recall('u','s'); assert got['working'][0]['content']=='hi' and got['summaries'][0]['summary']=='sum'
def test_skills_hot_reload_and_corrupt_fallback():
 with tempfile.TemporaryDirectory() as d:
  p=Path(d)/'PolicyRAGAgent.json'; p.write_text('{"rules":["old"]}',encoding='utf8'); r=SkillRegistry(d); assert 'old' in r.inject('PolicyRAGAgent','x'); p.write_text('{"rules":["new"]}',encoding='utf8'); assert 'new' in r.inject('PolicyRAGAgent','x'); p.write_text('{broken',encoding='utf8'); assert 'new' in r.inject('PolicyRAGAgent','x')
def test_monitor_penalty_recovery():
 m=AgentHealthMonitor(window_size=4)
 for _ in range(3):m.record('A',success=False,latency_ms=10)
 high=m.penalty('A'); assert high>.5
 for _ in range(4):m.record('A',success=True,latency_ms=10)
 assert m.penalty('A')<high
def test_judge_batch_heuristic():
 result=asyncio.run(LLMJudge().evaluate_batch([{'query':'refund','answer':'refund policy is available and you can apply now'}])); assert result['count']==1 and result['average']>0
def test_gateway_transport_trace():
 async def transport(**kw): return {'tool':kw['name'],'trace':kw['trace_id']}
 async def run():
  r=await DistributedToolGateway(transport=transport).call('lookup',trace_id='trace-1',sku='x'); assert r.success and r.trace_id=='trace-1' and r.data['tool']=='lookup'
 asyncio.run(run())
async def test_runtime_does_not_leak_or_persist_memory():
 from app.agentflow_adapter.runtime import AgentFlowRuntime
 async def legacy():return {'reply':'ok','executed_route':'legacy_langgraph_chat'}
 m=MemoryManager(); rt=AgentFlowRuntime(memory=m)
 result=await rt.handle('hello',legacy,session_id='session',user_id='user'); await asyncio.sleep(0)
 assert await m.get_working('session')==[]
 assert 'memory' not in result['metadata']
async def test_three_way_fusion_fake_providers():
 class E:
  def embed_query(self,t):return [1.,0.]
  def embed_documents(self,ts):return [[1.,0.] for _ in ts]
 class L:
  def invoke(self,p):return type('R',(),{'content':'{"intent":"policy_faq","confidence":0.9}'})()
 r=await IntentRouter(llm=L(),embeddings=E()).classify_async('请问其他问题')
 assert r.evidence['source']=='llm_embedding_pattern' and r.primary_intent=='policy_faq'
