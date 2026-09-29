from pathlib import Path
p=Path('app/services/chat_service.py')
lines=p.read_text(encoding='utf-8-sig').splitlines()
for i,l in enumerate(lines):
    if '"""' in l and l.rstrip().endswith('""') and not l.rstrip().endswith('"""'):
        lines[i]=l+'"'
# first module docstring line should close with triple quote as well
if lines and lines[0].count('"') < 6:
    lines[0] += '"'
p.write_text('\n'.join(lines)+'\n', encoding='utf-8')
