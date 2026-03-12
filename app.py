# ================== app.py (ИСПРАВЛЕННАЯ ВЕРСИЯ ДЛЯ RENDER) ==================
import os
import re
import math
import logging
from flask import Flask, request, render_template_string, redirect, url_for, session, flash

import cloudscraper
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key-change-me-2026")

# Логирование (видно в Render Logs)
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# ================== РЕЙТИНГИ + АЛГОРИТМ (без изменений) ==================
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
    eg_c = team_chances * 0.35 * prob_score(att_c / def_opp_c)
    eg_l = team_chances * 0.25 * prob_score(att_l / def_opp_r)
    eg_r = team_chances * 0.25 * prob_score(att_r / def_opp_l)
    eg_sp = team_chances * 0.15 * 0.12
    return eg_c + eg_l + eg_r + eg_sp

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
        if m:
            center_poss = float(m.group(1))
            break
    ratings = re.findall(r'(Wretched|Poor|Weak|Inadequate|Passable|Solid|Excellent|Formidable|Outstanding|Brilliant|Magnificent|World Class|Supernatural|Titanic|Extraterrestrial|Mythical|Utopian|Divine|Ужасный|Жалкий|Бедный|Слабый|Недостаточный|Приемлемый|Твёрдый|Отличный|Грозный|Выдающийся|Блестящий|Великолепный|Мирового класса|Сверхъестественный|Титанический|Внеземной|Мифический|Утопический|Божественный)\s*[-–]?\s*(very low|low|high|very high|очень низкий|низкий|высокий|очень высокий)?', text, re.I)
    nums = [text_to_rating(f"{lvl} {sub or ''}") for lvl, sub in ratings[:20] if text_to_rating(f"{lvl} {sub or ''}") > 1]
    if len(nums) < 14:
        raise ValueError(f"Не удалось найти рейтинги игроков (найдено {len(nums)})")
    home = {"gk":nums[0],"def_l":nums[1],"def_c":nums[2],"def_r":nums[3],"mid":nums[4],"att_l":nums[5],"att_c":nums[6],"att_r":nums[7]}
    away = {"gk":nums[8],"def_l":nums[9],"def_c":nums[10],"def_r":nums[11],"mid":nums[12],"att_l":nums[13],"att_c":nums[14] if len(nums)>14 else nums[6],"att_r":nums[15] if len(nums)>15 else nums[7]}
    return home, away, poss45, poss90, center_poss

# ================== СКРАПЕР ==================
def get_scraper():
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    if "hattrick_cookies" in session:
        scraper.cookies.update(session["hattrick_cookies"])
    return scraper

def save_cookies(scraper):
    session["hattrick_cookies"] = dict(scraper.cookies)

# ================== ОБРАБОТЧИК ОШИБОК ==================
@app.errorhandler(Exception)
def handle_error(error):
    app.logger.error(f"Ошибка: {str(error)}")
    return render_template_string("""
        <h1>❌ Ошибка сервера</h1>
        <p>Проверь Logs в Render Dashboard.<br>Сообщение: {{ error }}</p>
        <a href="/">Вернуться</a>
    """, error=str(error)), 500

# ================== HTML-СТРАНИЦЫ ==================
HTML_LOGIN = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Hattrick Analyzer — Вход</title><style>body{font-family:Arial;max-width:600px;margin:50px auto;padding:20px;background:#f0f2f5;}input,button{padding:12px;margin:10px 0;width:100%;font-size:16px;}</style></head><body><h1>🔑 Вход в Hattrick</h1><form method="post"><input type="text" name="username" placeholder="Логин / email" required><input type="password" name="password" placeholder="Пароль" required><button type="submit">Войти</button></form></body></html>"""

HTML_MAIN = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Hattrick Analyzer</title><style>body{font-family:Arial;max-width:700px;margin:40px auto;padding:20px;background:#f0f2f5;}input,button{padding:15px;font-size:18px;width:100%;}</style></head><body><h1>⚽ Hattrick Match Analyzer</h1><form method="post"><input type="url" name="url" placeholder="https://www.hattrick.org/...MatchID=..." required><button type="submit">Анализировать матч</button></form><a href="/logout">Выйти</a></body></html>"""

HTML_RESULT = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Результат</title><style>body{font-family:Arial;max-width:700px;margin:40px auto;padding:20px;background:#f0f2f5;line-height:1.6;}</style></head><body><h1>✅ Результат анализа</h1><p><strong>🏠 Победа хозяев:</strong> {{ win_h }}%</p><p><strong>🤝 Ничья:</strong> {{ draw }}%</p><p><strong>🏟️ Победа гостей:</strong> {{ win_a }}%</p><p>Владение: 45' {{ p45 }}% | 90' {{ p90 }}% | Центр поля {{ center }}%</p><hr><a href="/">Ещё матч</a></body></html>"""

# ================== МАРШРУТЫ ==================
@app.route("/", methods=["GET", "POST"])
def index():
    if "hattrick_cookies" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        url = request.form.get("url", "").strip()
        if "MatchID=" not in url:
            flash("Нужна ссылка с MatchID!")
            return redirect(url_for("index"))
        try:
            scraper = get_scraper()
            r = scraper.get(url, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            home, away, p45, p90, center = parse_report_text(soup.get_text())
            win_h, draw, win_a = calculate_match_prob(home, away, p45, p90, center)
            return render_template_string(HTML_RESULT, win_h=win_h, draw=draw, win_a=win_a, p45=p45, p90=p90, center=center)
        except Exception as e:
            flash(f"Ошибка анализа: {str(e)}")
            return redirect(url_for("index"))

    return render_template_string(HTML_MAIN)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            username = request.form["username"].strip()
            password = request.form["password"].strip()
            scraper = get_scraper()
            login_url = "https://www.hattrick.org/Login.aspx"

            r = scraper.get(login_url, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # ЗАЩИЩЁННЫЙ парсинг (не упадёт на None)
            def get_value(name):
                tag = soup.find("input", {"name": name})
                return tag.get("value", "") if tag else ""

            data = {
                "__VIEWSTATE": get_value("__VIEWSTATE"),
                "__VIEWSTATEGENERATOR": get_value("__VIEWSTATEGENERATOR"),
                "__EVENTVALIDATION": get_value("__EVENTVALIDATION"),
                "ctl00$ctl00$CPMain$CPLogin$txtLogin": username,
                "ctl00$ctl00$CPMain$CPLogin$txtPassword": password,
                "ctl00$ctl00$CPMain$CPLogin$btnLogin": "Log in",
            }

            post = scraper.post(login_url, data=data, timeout=15)

            if any(word in post.text.lower() for word in ["logout", "выход", "log out"]):
                save_cookies(scraper)
                flash("✅ Успешный вход!")
                return redirect(url_for("index"))
            else:
                flash("❌ Неправильный логин/пароль или форма изменилась")
        except Exception as e:
            app.logger.error(f"Ошибка логина: {str(e)}")
            flash(f"Ошибка входа: {str(e)}")

    return render_template_string(HTML_LOGIN)

@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли")
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
