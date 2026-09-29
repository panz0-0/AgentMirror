from pathlib import Path
p=Path('app/services/chat_service.py')
lines=p.read_text(encoding='utf-8').splitlines()
repl={
152:'            {"type": "tryon", "label": "查看上身效果图", "sku_id": sku.id},',
170:'    lines.append("点击下方按钮查看试穿效果图。")',
194:'        intro = f"亲亲，按您的描述，我在店里找到了相似的 **{name}**～"',
314:'    tryon_kw = ("试穿", "试试", "上身", "效果图", "穿搭", "穿上")',
341:'    intro_kw = ("介绍一下", "介绍", "这个商品")',
354:'    browse_exact = ("有哪些商品", "有什么商品", "店里有什么", "店铺商品", "女装有哪些", "衣服有哪些", "商品列表", "全部商品")',
368:'                        {"name": g.get("name", "未分类"), "count": g.get("count", 0)}',
372:'                        {"type": "message", "label": "虚拟试穿效果图", "text": "我想试穿这件衣服"},',
373:'                        {"type": "message", "label": "发货查询", "text": "几天发货？"},',
387:'        lines = [f"亲亲，店里目前有 **{cat[\'total\']}** 款商品～"]',
389:'            names = "、".join(i["name"] for i in g["items"][:4])',
397:'                {"type": "message", "label": "虚拟试穿效果图", "text": "我想试穿这件衣服"},',
398:'                {"type": "message", "label": "发货查询", "text": "几天发货？"},',
426:'        if "暂未找到相关知识库内容" not in answer:',
450:'    reply = result.get("reply_text", "抱歉，我暂时无法回答。")',
505:'                prefix = "根据您发送的图片：" if not text else f"结合您的描述“{text}”，"',
583:'    body_note = "（使用您的身材数据）" if not body["is_default"] else "（使用运营台默认标准身材）"',
594:'        "完整模特效果图可在运营台生成后查看。"',
605:'    body_note = "（使用您的身材数据）" if not body["is_default"] else "（使用运营台默认标准身材）"',
609:'        "运营台尚未生成模特上身图，请先在运营台完成“生成图片”后再查看试穿效果。"',
}
for n,v in repl.items(): lines[n-1]=v
p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
