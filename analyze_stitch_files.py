import re
from pathlib import Path

base = Path('stitch_platform')
for p in sorted(base.iterdir()):
    if p.is_dir() and (p / 'code.html').exists():
        text = (p / 'code.html').read_text(encoding='utf-8')
        title_m = re.search(r'<title>(.*?)</title>', text)
        title = title_m.group(1) if title_m else 'No title'
        has_script = '<script>' in text or '<script ' in text
        script_blocks = len(re.findall(r'<script(?![^>]*src)[^>]*>([\s\S]*?)</script>', text))
        body_len = len(text[text.find('<body'):text.rfind('</body>')]) if '<body' in text else 0
        print(f"{p.name:45} | {title:35} | {body_len:6}b body | {script_blocks} inline scripts")
