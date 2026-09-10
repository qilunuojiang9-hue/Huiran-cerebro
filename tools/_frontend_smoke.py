#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""赛博大脑前端冒烟测试：加载页面 -> 搜索 -> 点开详情抽屉 -> 实体关系 Tab"""
import os
import time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8899"

def main():
    errors, warnings = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.on("console", lambda m: (errors if m.type == "error" else warnings).append(m.text))
        pg.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))

        pg.goto(BASE, wait_until="networkidle", timeout=60000)
        print("1) 页面标题:", pg.title())

        # Tab 是否都在
        tabs = pg.eval_on_selector_all(".tab", "els=>els.map(e=>e.textContent)")
        print("2) Tab 列表:", tabs)

        # 统计是否加载（statGrid 位于默认隐藏的「浏览」面板，用 attached 而非 visible）
        pg.wait_for_selector("#statGrid .stat", state="attached", timeout=15000)
        stat_txt = pg.eval_on_selector("#statGrid", "e=>e.textContent||''")
        print("3) 统计块已渲染，字符数:", len(stat_txt))

        # 搜索
        pg.fill("#q", "德孚润滑油")
        pg.click("button.btn.blue")
        pg.wait_for_timeout(3500)
        # 等语义检索结果（较慢）
        cards = pg.eval_on_selector_all("#results .card", "els=>els.length")
        items = pg.eval_on_selector_all("#results .item", "els=>els.length")
        print(f"4) 搜索结果: {cards} 个分组卡片 / {items} 条结果条目")

        # 分组筛选 chip
        chips = pg.eval_on_selector_all("#results .filterbar .fchip", "els=>els.map(e=>e.textContent)")
        print("5) 分组筛选 chip:", chips)

        # 点击第一条可点击结果 -> 详情抽屉
        first = pg.query_selector("#results .item[data-kind]:not([data-kind='x'])")
        if first:
            kind = first.get_attribute("data-kind")
            kind_id = first.get_attribute("data-id")
            first.scroll_into_view_if_needed()
            first.click()
            pg.wait_for_selector("#drawer.show", timeout=15000)
            pg.wait_for_timeout(900)
            title = pg.inner_text("#drawerTitle")
            body_len = len(pg.inner_text("#drawerBody"))
            print(f"6) 点击结果(kind={kind},id={kind_id}) -> 抽屉标题: {title!r} | 正文长度: {body_len}")
            has_md = pg.eval_on_selector_all("#drawerBody .md, #drawerBody .md h1, #drawerBody .md h2, #drawerBody .md li", "els=>els.length")
            print("7) 抽屉内 Markdown 节点数:", has_md)
        else:
            print("6) 未找到可点击结果（跳过抽屉测试）")

        # 关闭抽屉
        pg.keyboard.press("Escape") if False else pg.click("#overlay", position={"x":80,"y":320})
        pg.wait_for_timeout(600)
        visible = pg.eval_on_selector("#drawer", "e=>e.classList.contains('show')")
        print("8) 抽屉已关闭:", not visible)

        # 实体关系 Tab
        pg.click(".tab[data-tab='rel']")
        pg.wait_for_timeout(500)
        pg.fill("#relQ", "汉全科技")
        pg.click("#panel-rel button.btn.blue")
        pg.wait_for_timeout(2500)
        matches = pg.eval_on_selector_all("#relMatches .rel", "els=>els.map(e=>e.textContent)")
        print("9) 实体关系匹配数:", len(matches))
        for m in matches[:4]:
            print("     -", m.strip())

        if matches:
            pg.query_selector("#relMatches .rel").click()
            pg.wait_for_selector("#drawer.show", timeout=15000)
            pg.wait_for_timeout(1200)
            print("10) 实体抽屉标题:", pg.inner_text("#drawerTitle"))
            rels = pg.eval_on_selector_all("#drawerBody .rel", "els=>els.length")
            print("11) 关系节点数:", rels)
            txt = pg.inner_text("#drawerBody")
            print("12) 抽屉含'关系网络'标题:", "关系网络" in txt)
            pg.click("#overlay", position={"x":80,"y":320})
            pg.wait_for_timeout(400)

        # 浏览 Tab
        pg.click(".tab[data-tab='browse']")
        pg.wait_for_timeout(2500)
        rows = pg.eval_on_selector_all("#listBody .item", "els=>els.length")
        print("13) 浏览 Tab 列表条目数:", rows)

        pg.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke_shot.png"), full_page=False)
        b.close()

    print("\n=== 控制台 error ===")
    print("\n".join(errors) if errors else "（无）")
    print("=== 控制台 warning ===")
    print("\n".join(warnings[:8]) if warnings else "（无）")

if __name__ == "__main__":
    main()
