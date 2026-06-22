from pathlib import Path
from bs4 import BeautifulSoup

count = 0
for f in Path('site').rglob('*.html'):
    html = f.read_text()
    if 'Connector Configuration' in html:
        soup = BeautifulSoup(html, 'html.parser')
        h1 = soup.find('h1')
        title = h1.get_text(strip=True) if h1 else 'No H1'
        print(f.name, "-> Title:", title)
        count += 1
print("Count:", count)
