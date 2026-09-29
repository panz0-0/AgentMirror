from pathlib import Path
for i,l in enumerate(Path('app/services/chat_service.py').read_text(encoding='utf8').splitlines(),1):
 if 267<=i<=275: print(i,repr(l))
