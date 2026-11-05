# Drives web/index.html in headless Chromium at phone and desktop sizes: solving the first level by
# taps, progress after a reload, locked episodes and "Unlock all episodes", show solution, the
# editor, export, save and test. Screenshots go to OUTDIR.
#   .venv/bin/pip install playwright && .venv/bin/python -m playwright install chromium
#   .venv/bin/python web/test/ui_test.py OUTDIR
import json
import os
import sys
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
URL = 'file://' + os.path.abspath(os.path.join(HERE, '..', 'index.html'))
FIRST = json.load(open(os.path.join(HERE, '..', '..', 'designs', 'episodes.json')))['levels'][0]
OUT = os.path.join(sys.argv[1] if len(sys.argv) > 1 else '.', '')
errors = []

def tap_cell(page, x, y):
    box = page.locator('#board').bounding_box()
    s = box['width'] / 15.5
    page.mouse.click(box['x'] + (x + 0.75) * s, box['y'] + (y + 0.75) * s)

def open_level(page, pack_name, n):
    page.click('#menuBtn')
    det = page.locator('details.pack', has=page.locator('strong', has_text=pack_name)).first
    if not det.evaluate('d => d.open'):
        det.locator('summary').click()
    det.locator('.levels button', has_text=str(n)).first.click()

def run(p, name, **ctx):
    browser = p.chromium.launch()
    context = browser.new_context(**ctx)
    page = context.new_page()
    page.on('console', lambda m: m.type == 'error' and errors.append(f'{name}: {m.text}'))
    page.on('pageerror', lambda e: errors.append(f'{name}: {e}'))
    page.goto(URL)
    page.screenshot(path=OUT + f'{name}-1-start.png')
    print(name, 'start:', page.locator('#packName').inner_text(), '|', page.locator('#levelTitle').inner_text())
    # the first level by taps: place each piece, then tap it once per 45-degree turn
    tools = page.locator('#toolbox .tool')
    for i, s in enumerate(FIRST['solution']):
        tools.nth(i).click(); tap_cell(page, s['x'], s['y'])
        for _ in range(s['dir']):
            tap_cell(page, s['x'], s['y'])
    page.wait_for_timeout(100)
    print(name, 'banner after taps:', page.locator('#banner').inner_text() if page.locator('#banner').is_visible() else 'NOT SHOWN')
    page.screenshot(path=OUT + f'{name}-2-solved.png')
    page.reload()
    print(name, 'after reload:', page.locator('#packName').inner_text(), '|', page.locator('#levelTitle').inner_text())
    page.click('#nextBtn')
    page.click('#moreBtn'); page.click('#moreMenu button:has-text("Show solution")')
    print(name, 'show solution:', page.locator('#banner').inner_text(), '| title', page.locator('#levelTitle').inner_text())
    page.click('#menuBtn'); page.wait_for_timeout(100)
    print(name, 'locked episodes:', page.locator('details.pack.locked').count(),
          '| note:', page.locator('.lock-note').first.text_content())
    page.screenshot(path=OUT + f'{name}-3-menu.png')
    page.click('#drawerClose')
    page.click('#moreBtn'); page.click('#moreMenu button:has-text("Unlock all episodes")')
    page.click('#menuBtn'); page.wait_for_timeout(100)
    print(name, 'locked after unlock all:', page.locator('details.pack.locked').count())
    page.click('#drawerClose')
    open_level(page, 'Episode 6', 2)
    print(name, 'episode 6:', page.locator('#packName').inner_text(), '|', page.locator('#levelTitle').inner_text())
    page.screenshot(path=OUT + f'{name}-4-ep6.png')
    page.click('#moreBtn'); page.click('#moreMenu button:has-text("Edit a copy")')
    page.wait_for_timeout(100)
    print(name, 'editor status:', page.locator('#edStatus').inner_text().replace('\n', ' / '))
    page.screenshot(path=OUT + f'{name}-5-editor.png', full_page=True)
    page.click('#edExport')
    text = page.locator('#textDialogText').input_value()
    print(name, 'export first lines:', text.splitlines()[:4])
    page.click('dialog button[value=cancel]')
    page.click('#edSave')
    print(name, 'after save:', page.locator('#packName').inner_text())
    page.click('#edTest')
    page.click('#moreBtn'); page.click('#moreMenu button:has-text("Show solution")')
    print(name, 'test + solution:', page.locator('#banner').inner_text())
    page.click('#backToEditor')
    print(name, 'back in editor:', page.locator('#editPanel').is_visible())
    browser.close()

with sync_playwright() as p:
    run(p, 'phone', viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=2)
    run(p, 'desktop', viewport={'width': 1400, 'height': 900})
print('errors:', errors or 'none')
sys.exit(1 if errors else 0)
