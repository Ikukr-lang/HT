# ================== app.py (ПРОСТАЯ ВЕРСИЯ — ТОЛЬКО РУЧНОЙ ВВОД ТАБЛИЦ) ==================
import os
import re
import math
import logging
from flask import Flask, request, render_template_string, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "super-secret-key-2026")

logging.basicConfig(level=logging.INFO)

# ================== АЛГОРИТМ HATTRICK ==================
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

# ================== ПАРСЕР BBCode-ТАБЛИЦ (точно по формату форума) ==================
def parse_team_table(bbcode: str) -> dict:
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
        # Основной поиск по [td align=right]число[/td]
        pattern = rf'{re.escape(pos_name)}[\s\S]*?align=right\]([\d,]+)\[/td\]'
        m = re.search(pattern, bbcode, re.IGNORECASE)
        if m:
            data[key] = float(m.group(1).replace(',', '.'))
            continue
        # Запасной поиск числа
        pattern2 = rf'{re.escape(pos_name)}[^0-9]*?(\d+)[,.](\d+)'
        m2 = re.search(pattern2, bbcode, re.IGNORECASE | re.DOTALL)
        if m2:
            data[key] = float(m2.group(1) + '.' + m2.group(2))
    return data

# ================== HTML ==================
HTML_MAIN = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Hattrick Analyzer — Ручной ввод</title>
    <style>
        body{font-family:Arial;max-width:900px;margin:40px auto;padding:20px;background:#f0f2f5;line-height:1.6;}
        textarea{width:100%; height:320px; font-family:monospace; font-size:14px; margin-bottom:15px;}
        input[type=number]{width:80px; padding:8px;}
        button{padding:15px 40px; font-size:18px; background:#0066cc; color:white; border:none; cursor:pointer;}
        h3{margin-top:25px;}
    </style>
</head>
<body>
    <h1>⚽ Hattrick Match Analyzer</h1>
    <p><strong>Как пользоваться:</strong> Скопируй полностью [table]...[/table] с форума для каждой команды и вставь ниже.</p>
    
    <form method="post">
        <h3>🏠 Домашняя команда</h3>
        <textarea name="home_table" placeholder="Вставь сюда всю таблицу домашней команды (начиная с [table] и заканчивая [/table])" required></textarea>
        
        <h3>🏟️ Гостевая команда</h3>
        <textarea name="away_table" placeholder="Вставь сюда всю таблицу гостевой команды" required></textarea>
        
        <h3>Владение мячом</h3>
        <table style="width:100%; border-collapse:collapse;">
            <tr>
                <td style="padding:8px;">45 минута:</td>
                <td><input type="number" name="p45" value="50" step="0.1"> %</td>
            </tr>
            <tr>
                <td style="padding:8px;">90 минута:</td>
                <td><input type="number" name="p90" value="50" step="0.1"> %</td>
            </tr>
            <tr>
                <td style="padding:8px;">Центр поля:</td>
                <td><input type="number" name="center" value="50" step="0.1"> %</td>
            </tr>
        </table>
        
        <button type="submit" style="margin-top:20px;">Посчитать вероятности матча</button>
    </form>
</body>
</html>"""

HTML_RESULT = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <title>Результат анализа</title>
    <style>
        body{font-family:Arial;max-width:700px;margin:40px auto;padding:20px;background:#f0f2f5;line-height:1.6;}
    </style>
</head>
<body>
    <h1>✅ Результат анализа</h1>
    <p><strong>🏠 Победа хозяев:</strong> {{ win_h }}%</p>
    <p><strong>🤝 Ничья:</strong> {{ draw }}%</p>
    <p><strong>🏟️ Победа гостей:</strong> {{ win_a }}%</p>
    <p>Владение: 45' {{ p45 }}% | 90' {{ p90 }}% | Центр поля {{ center }}%</p>
    <hr>
    <a href="/" style="font-size:18px;">← Ещё один матч</a>
</body>
</html>"""

# ================== МАРШРУТЫ ==================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
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
            flash(f"Ошибка парсинга: {str(e)}<br>Убедись, что таблицы вставлены полностью и содержат рейтинги.")
            return redirect("/")
    
    return render_template_string(HTML_MAIN)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
