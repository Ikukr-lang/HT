# ================== app.py (УЛУЧШЕННАЯ ВЕРСИЯ — COOKIES + РУЧНОЙ ВВОД BBCode-таблиц) ==================
import os
import re
import math
import logging
from flask import Flask, request, render_template_string, redirect, url_for, session, flash
from http.cookies import SimpleCookie

import cloudscraper
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key-2026")

logging.basicConfig(level=logging.INFO)

# ================== АЛГОРИТМ HATTRICK (без изменений) ==================
LEVELS_EN = {"disastrous":1,"wretched":2,"poor":3,"weak":4,"inadequate":5,"passable":6,"solid":7,"excellent":8,"formidable":9,"outstanding":10,"brilliant":11,"magnificent":12,"world class":13,"supernatural":14,"titanic":15,"extraterrestrial":16,"mythical":17,"utopian":18,"divine":19}
LEVELS_RU = {"ужасный":1,"жалкий":2,"бедный":3,"слабый":4,"недостаточный":5,"приемлемый":6,"твёрдый":7,"отличный":8,"грозный":9,"выдающийся":10,"блестящий":11,"великолепный":12,"мирового класса":13,"сверхъестественный":14,"титанический":15,"внеземной":16,"мифический":17,"утопический":18,"божественный":19}
SUBS_EN = {"very low":0.0,"low":0.25,"high":0.5,"very high":0.75}
SUBS_RU = {"очень низкий":0.0,"низкий":0.25,"высокий":0.5,"очень высокий":0.75}

def text_to_rating(text: str) -> float:
    text = text.lower().strip()
    for lvl_str, val in LEVELS_EN.items():
        if lvl_str in text:
            base = val
            for s, v in SUBS_EN.items():
                if s in text: return base + v
            return base
    for lvl_str, val in LEVELS_RU.items():
        if lvl_str in text:
            base = val
            for s, v in SUBS_RU.items():
                if s in text: return base + v
            return base
    return 1.0

def poisson_pmf(k: int, lam: float) -> float:
    if lam == 0: return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def prob_score(ratio: float) -> float:
    return max(0.05, min(0.45, 0.05 + 0.35 / (1 + math.exp(-(ratio - 1) * 2))))

def get_expected_goals(att_l, att_c, att_r, def_opp_r, def_opp_c, def_opp_l, possession):
    total = 10.0
    team_chances = total * possession
    return (team_chances * 0.35 * prob_score(att_c / def_opp_c) +
            team_chances * 0.25 * prob_score(att_l / def_opp_r) +
            team_chances * 0.25 * prob_score(att_r / def_opp_l) +
            team_chances * 0.15 * 0.12)

def calculate_match_prob(home, away, p45, p90, center_poss=50.0):
    poss_home = (p45 + p90) / 200.0
    if center_poss > 0:
        poss_home = poss_home * 0.7 + center_poss / 100 * 0.3
    home_lam = get_expected_goals(home["att_l"],home["att_c"],home["att_r"], away["def_r"],away["def_c"],away["def_l"], poss_home)
    away_lam = get_expected_goals(away["att_l"],away["att_c"],away["att_r"], home["def_r"],home["def_c"],home["def_l"], 1-poss_home)
    MAX_G = 10
    h_probs = [poisson_pmf(k, home_lam) for k in range(MAX_G+1)]
    a_probs = [poisson_pmf(k, away_lam) for k in range(MAX_G+1)]
    win_h = draw = win_a = 0.0
    for h in range(MAX_G+1):
        for a in range(MAX_G+1):
            p = h_probs[h] * a_probs[a]
            if h > a: win_h += p
            elif h == a: draw += p
            else: win_a += p
    return round(win_h*100), round(draw*100), round(win_a*100)

def parse_report_text(text: str):
    poss45 = poss90 = center_poss = 50.0
    m = re.search(r"45['′]?\D*(\d+)%", text, re.I)
    if m: poss45 = float(m.group(1))
    m = re.search(r"90['′]?\D*(\d+)%", text, re.I)
    if m: poss90 = float(m.group(1))
    for pat in [r"центр.*?(\d+)%", r"center.*?(\d+)%", r"midfield.*?(\d+)%", r"владения в центре.*?(\d+)%"]:
        m = re.search(pat, text, re.I)
        if m: center_poss = float(m.group(1))
    ratings = re.findall(r'(Wretched|Poor|Weak|Inadequate|Passable|Solid|Excellent|Formidable|Outstanding|Brilliant|Magnificent|World Class|Supernatural|Titanic|Extraterrestrial|Mythical|Utopian|Divine|Ужасный|Жалкий|Бедный|Слабый|Недостаточный|Приемлемый|Твёрдый|Отличный|Грозный|Выдающийся|Блестящий|Великолепный|Мирового класса|Сверхъестественный|Титанический|Внеземной|Мифический|Утопический|Божественный)\s*[-–]?\s*(very low|low|high|very high|очень низкий|низкий|высокий|очень высокий)?', text, re.I)
    nums = [text_to_rating(f"{lvl} {sub or ''}") for lvl, sub in ratings[:20] if text_to_rating(f"{lvl} {sub or ''}") > 1]
    if len(nums) < 14:
        raise ValueError(f"Рейтингов найдено только {len(nums)}")
    home = {"gk":nums[0],"def_l":nums[1],"def_c":nums[2],"def_r":nums[3],"mid":nums[4],"att_l":nums[5],"att_c":nums[6],"att_r":nums[7]}
    away = {"gk":nums[8],"def_l":nums[9],"def_c":nums[10],"def_r":nums[11],"mid":nums[12],"att_l":nums[13],"att_c":nums[14] if len(nums)>14 else nums[6],"att_r":nums[15] if len(nums)>15 else nums[7]}
    return home, away, poss45, poss90, center_poss

# ================== НОВЫЙ ПАРСЕР ДЛЯ BBCode-ТАБЛИЦ (точно по формату форума) ==================
def parse_team_table(bbcode: str) -> dict:
    """Парсит [table] с форума Hattrick и возвращает рейтинги команды"""
    data = {"def_l": 5.0, "def_c": 5.0, "def_r": 5.0,
            "mid": 5.0,
            "att_l": 5.0, "att_c": 5.0, "att_r": 5.0}
    
    mappings = {
        "Защита слева": "def_l",
        "Защита по центру": "def_c",
        "Защита справа": "def_r",
        "Полузащита": "mid",
        "Атака слева": "att_l",
        "Атака по центру": "att_c",
        "Атака справа": "att_r"
    }
    
    for pos_name, key in mappings.items():
        # Основной поиск: после названия позиции — число в [td align=right]X,XX[/td]
        pattern = rf'{re.escape(pos_name)}[\s\S]*?align=right\]([\d,]+)\[/td\]'
        m = re.search(pattern, bbcode, re.IGNORECASE)
        if m:
            data[key] = float(m.group(1).replace(',', '.'))
            continue
        # Запасной вариант (просто число после названия)
        pattern2 = rf'{re.escape(pos_name)}[^0-9]*?(\d+)[,.](\d+)'
        m2 = re.search(pattern2, bbcode, re.IGNORECASE | re.DOTALL)
        if m2:
            data[key] = float(m2.group(1) + '.' + m2.group(2))
    return data

# ================== COOKIES ==================
def get_scraper():
    scraper = cloudscraper.create_scraper()
    if "hattrick_cookies" in session:
        scraper.cookies.update(session["hattrick_cookies"])
    return scraper

def save_cookies(scraper):
    session["hattrick_cookies"] = dict(scraper.cookies)

# ================== HTML ==================
HTML_COOKIES = """
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Hattrick Analyzer — Cookies</title><style>body{font-family:Arial;max-width:800px;margin:40px auto;padding:20px;background:#f0f2f5;line-height:1.6;}</style></head>
<body>
<h1>🔑 Авторизация через cookies (hattrick.org)</h1>
<p><strong>Самый простой способ (работает в 2026 году):</strong></p>
<ol>
<li>Открой <a href="https://www.hattrick.org" target="_blank">hattrick.org</a> и войди в свой аккаунт</li>
<li>Нажми <strong>F12</strong> → вкладка <strong>Application</strong> (или <strong>Storage</strong>)</li>
<li>В левом меню: <strong>Cookies → https://www.hattrick.org</strong></li>
<li>Выдели все cookies (Ctrl + A)</li>
<li>Правой кнопкой → Copy</li>
<li>Вставь сюда</li>
</ol>

<p><strong>Ещё проще — расширение Chrome:</strong><br>
<a href="https://chromewebstore.google.com/detail/copy-cookies/jcbpglbplpblnagieibnemmkiamekcdg" target="_blank">Установить «Copy Cookies»</a></p>

<form method="post">
    <textarea name="cookies" rows="8" placeholder="Вставь сюда cookies (name=value; name2=value2)" style="width:100%; font-family:monospace;" required></textarea>
    <button type="submit" style="padding:15px;font-size:18px;">Сохранить cookies и войти</button>
</form>
</body></html>
"""

HTML_MAIN = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Hattrick Analyzer</title>
<style>
    body{font-family:Arial;max-width:900px;margin:40px auto;padding:20px;background:#f0f2f5;}
    .tab {overflow:hidden; border-bottom:1px solid #ccc;}
    .tab button {background:none;border:none;padding:12px 20px;cursor:pointer;font-size:16px;}
    .tab button.active {border-bottom:3px solid #0066cc;color:#0066cc;}
    textarea {width:100%; height:280px; font-family:monospace; font-size:14px;}
</style>
</head>
<body>
<h1>⚽ Hattrick Match Analyzer</h1>

<div class="tab">
    <button onclick="openTab(0)" class="active">По ссылке на матч</button>
    <button onclick="openTab(1)">Ручной ввод таблиц</button>
</div>

<!-- === Форма 1: По ссылке === -->
<div id="tab0">
    <form method="post">
        <input type="url" name="url" placeholder="https://www.hattrick.org/...MatchID=..." style="width:100%;padding:10px;" required>
        <button type="submit" style="padding:12px 30px;font-size:18px;margin-top:10px;">Анализировать матч</button>
    </form>
    <a href="/set_cookies">Обновить cookies</a>
</div>

<!-- === Форма 2: Ручной ввод (именно то, что просил пользователь) === -->
<div id="tab1" style="display:none;">
    <form method="post">
        <input type="hidden" name="manual_mode" value="1">
        
        <h3>🏠 Домашняя команда (вставьте всю [table]...[/table])</h3>
        <textarea name="home_table" placeholder="Вставьте таблицу домашней команды (с [matchid=...] и всеми строками)" required></textarea>
        
        <h3>🏟️ Гостевая команда (вставьте всю [table]...[/table])</h3>
        <textarea name="away_table" placeholder="Вставьте таблицу гостевой команды" required></textarea>
        
        <h3>Владение мячом</h3>
        <table style="width:100%">
            <tr><td>45 минута:</td><td><input type="number" name="p45" value="50" style="width:80px" step="0.1"> %</td></tr>
            <tr><td>90 минута:</td><td><input type="number" name="p90" value="50" style="width:80px" step="0.1"> %</td></tr>
            <tr><td>Центр поля:</td><td><input type="number" name="center" value="50" style="width:80px" step="0.1"> %</td></tr>
        </table>
        
        <button type="submit" style="padding:15px 40px;font-size:18px;margin-top:15px;background:#0066cc;color:white;">
            Посчитать вероятности
        </button>
    </form>
</div>

<script>
function openTab(n) {
    document.getElementById('tab0').style.display = n===0 ? 'block' : 'none';
    document.getElementById('tab1').style.display = n===1 ? 'block' : 'none';
    document.querySelectorAll('.tab button').forEach((b,i)=> b.classList.toggle('active', i===n));
}
</script>
</body></html>"""

HTML_RESULT = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Результат</title><style>body{font-family:Arial;max-width:700px;margin:40px auto;padding:20px;background:#f0f2f5;line-height:1.6;}</style></head><body><h1>✅ Результат анализа</h1><p><strong>🏠 Победа хозяев:</strong> {{ win_h }}%</p><p><strong>🤝 Ничья:</strong> {{ draw }}%</p><p><strong>🏟️ Победа гостей:</strong> {{ win_a }}%</p><p>Владение: 45' {{ p45 }}% | 90' {{ p90 }}% | Центр поля {{ center }}%</p><hr><a href="/">Ещё матч</a></body></html>"""

# ================== МАРШРУТЫ ==================
@app.route("/set_cookies", methods=["GET", "POST"])
def set_cookies():
    if request.method == "POST":
        cookie_str = request.form["cookies"].strip()
        if cookie_str.startswith("Cookie:"):
            cookie_str = cookie_str[7:].strip()
        try:
            cookie = SimpleCookie()
            cookie.load(cookie_str)
            scraper = cloudscraper.create_scraper()
            for key, morsel in cookie.items():
                scraper.cookies.set(key, morsel.value)
            r = scraper.get("https://www.hattrick.org", timeout=10)
            if any(w in r.text.lower() for w in ["logout", "выход", "log out", "my hattrick"]):
                save_cookies(scraper)
                flash("✅ Cookies сохранены! Ты авторизован.")
                return redirect("/")
            else:
                flash("❌ Cookies не подошли.")
        except Exception as e:
            flash(f"Ошибка: {str(e)}")
    return render_template_string(HTML_COOKIES)

@app.route("/", methods=["GET", "POST"])
def index():
    if "hattrick_cookies" not in session:
        return redirect("/set_cookies")
    
    if request.method == "POST":
        if request.form.get("manual_mode") == "1":
            # ================== НОВЫЙ РУЧНОЙ РЕЖИМ (по запросу пользователя) ==================
            home_table = request.form.get("home_table", "").strip()
            away_table = request.form.get("away_table", "").strip()
            if not home_table or not away_table:
                flash("Нужно вставить таблицы обеих команд!")
                return redirect("/")
            try:
                home = parse_team_table(home_table)
                away = parse_team_table(away_table)
                p45 = float(request.form.get("p45", 50))
                p90 = float(request.form.get("p90", 50))
                center = float(request.form.get("center", 50))
                
                win_h, draw, win_a = calculate_match_prob(home, away, p45, p90, center)
                return render_template_string(HTML_RESULT, 
                                              win_h=win_h, draw=draw, win_a=win_a, 
                                              p45=p45, p90=p90, center=center)
            except Exception as e:
                flash(f"Ошибка парсинга таблиц: {str(e)}")
                return redirect("/")
        
        else:
            # Старый режим по URL (остаётся работать)
            url = request.form.get("url", "").strip()
            if "MatchID=" not in url:
                flash("Нужна ссылка с MatchID!")
                return redirect("/")
            try:
                scraper = get_scraper()
                r = scraper.get(url, timeout=20)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                home, away, p45, p90, center = parse_report_text(soup.get_text())
                win_h, draw, win_a = calculate_match_prob(home, away, p45, p90, center)
                return render_template_string(HTML_RESULT, win_h=win_h, draw=draw, win_a=win_a, p45=p45, p90=p90, center=center)
            except Exception as e:
                flash(f"Ошибка: {str(e)}")
                return redirect("/")
    
    return render_template_string(HTML_MAIN)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
