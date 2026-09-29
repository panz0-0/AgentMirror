from pathlib import Path
for i,l in enumerate(Path('app/services/chat_service.py').read_text().splitlines(),1):
 q=l.count('"')
 if q%2: print(i,q,l)
