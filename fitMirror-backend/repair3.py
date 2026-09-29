from pathlib import Path
p=Path('app/services/chat_service.py')
lines=p.read_text(encoding='utf-8').splitlines()
lines[152]='            {"type": "message", "label": "适合什么尺码？", "text": f"我想买{sku.name}，适合什么尺码？"},'
lines[153]='            {"type": "message", "label": "搭配建议", "text": f"{sku.name}有什么搭配建议？"},'
p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
