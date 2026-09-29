from pathlib import Path
p=Path('app/services/chat_service.py')
s=p.read_text(encoding='utf-8')
s=''.join(' ' if 0xE000 <= ord(c) <= 0xF8FF else c for c in s)
p.write_text(s, encoding='utf-8')
