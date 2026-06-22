from pathlib import Path
from bs4 import BeautifulSoup
import os

count = 0
for f in Path('site').rglob('*.html'):
    html = f.read_text()
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text(strip=True)
        if title == "ADP Workforce Now":
            print(f.name, "->", [h.get_text(strip=True) for h in soup.find_all(['h1', 'h2', 'h3'])])
            count += 1
print("Count:", count)
