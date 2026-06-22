from pathlib import Path
site_dir = Path('site/en-us/articles')
count = 0
for md_file in site_dir.rglob('*.md'):
    with open(md_file, 'r') as f:
        first_line = f.readline().strip()
        if 'ADP' in first_line and 'Workforce' in first_line:
            print(f"FILE: {md_file.name} | TITLE: {first_line}")
