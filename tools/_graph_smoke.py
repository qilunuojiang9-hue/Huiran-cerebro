"""赛博大脑 · 关系图谱前端冒烟测试（Playwright）。
验证：图谱 Tab 可绘制节点 / 点击节点打开详情抽屉 / 无控制台报错。
用法：python _graph_smoke.py
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8899/"
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    pg = browser.new_page(viewport={"width": 1200, "height": 800})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append("PAGEERR:" + str(e)))

    pg.goto(URL, wait_until="networkidle", timeout=30000)
    pg.click("text=关系图谱", timeout=10000)
    pg.wait_for_timeout(2800)  # 等力导向稳定

    stats = pg.evaluate(
        """() => {
        const cv = document.getElementById('gcanvas');
        const ctx = cv.getContext('2d');
        const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
        let nw = 0;
        for (let i = 0; i < d.length; i += 4) {
            if (d[i] < 250 || d[i+1] < 250 || d[i+2] < 250) nw++;
        }
        Galpha = 0; Grun = false;  // 暂停动画，稳定取坐标
        const n = Gnodes[0];
        const rect = cv.getBoundingClientRect();
        const [sx, sy] = g2s(n.x, n.y);
        return {nonwhite: nw, x: rect.left + sx, y: rect.top + sy,
                name: n.name, total: Gnodes.length};
    }"""
    )
    print("canvas 非白像素数:", stats["nonwhite"], "| 节点总数:", stats["total"])
    print("点击目标节点:", stats["name"], "屏幕坐标:", round(stats["x"]), round(stats["y"]))

    pg.mouse.click(stats["x"], stats["y"])
    pg.wait_for_timeout(600)
    drawer_shown = pg.evaluate("() => document.getElementById('drawer').classList.contains('show')")
    title = pg.evaluate("() => document.getElementById('drawerTitle').textContent")
    print("点击后详情抽屉打开:", drawer_shown, "| 标题:", title)

    browser.close()

print("控制台错误数:", len(errors))
for e in errors[:10]:
    print("  -", e)
passed = stats["nonwhite"] > 100 and drawer_shown and len(errors) == 0
print("RESULT", "PASS" if passed else "CHECK")
sys.exit(0 if passed else 1)
