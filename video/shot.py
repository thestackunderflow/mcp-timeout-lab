from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1080,'height':1920})
    pg.goto('file:///w/frame0.html'); pg.screenshot(path='/w/frame0-hung.png'); b.close()
