import re

with open('index.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Let's find each screen's start and end index
screens = [m.start() for m in re.finditer(r'<div\s+id="([^"]+)"\s+class="screen[^"]*"', text)]
screen_names = re.findall(r'<div\s+id="([^"]+)"\s+class="screen[^"]*"', text)

for i in range(len(screens)):
    name = screen_names[i]
    start = screens[i]
    end = screens[i+1] if i+1 < len(screens) else text.find('<!-- GLOBAL MODALS:', start)
    line_start = text[:start].count('\n') + 1
    line_end = text[:end].count('\n') + 1
    print(f"{name:30} : lines {line_start:5} to {line_end:5}")
