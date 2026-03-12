# ================== app.py (полная версия для Render) ==================
import math
import os
import re
from flask import Flask, request, render_template_string
from PIL import Image
import pytesseract
import cloudscraper
from bs4 import BeautifulSoup

# ================== РЕЙТИНГИ ==================
LEVELS_EN = {
    "disastrous": 1, "wretched": 2, "poor": 3, "weak": 4, "inadequate": 5,
    "passable": 6, "solid": 7, "excellent": 8, "formidable": 9, "outstanding": 10,
    "brilliant": 11, "magnificent": 12, "world class": 13, "supernatural": 14,
    "titanic": 15, "extraterrestrial": 16, "mythical": 17, "utopian": 18, "divine": 19
}
LEVELS_RU = {
    "ужасный": 1, "жалкий": 2, "бедный": 3, "слабый": 4, "недостаточный": 5,
    "приемлемый": 6, "твёрдый": 7, "отличный": 8, "грозный": 9, "выдающийся": 10,
    "блестящий": 11, "великолепный": 12, "мирового класса": 13, "сверхъестественный": 14,
    "титанический": 15, "внеземной": 16, "мифический": 17, "утопический": 18, "божественный": 19
}
SUBS_EN = {"very low": 0.0, "low": 0.25, "high": 0.5, "very high": 0.75}
SUBS_RU = {"очень низкий": 0.0, "низкий": 0.25, "высокий": 0.5, "очень высокий": 0.75}

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

# ================== АЛГОРИТМ РАСЧЁТА (точно как в боте) ==================
def poisson_pmf(k: int, lam: float) -> float:
    if lam == 0: return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def prob_score(ratio: float) -> float:
    return max(0.05, min(0.45, 0.05 + 0.35 / (1 + math.exp(-(ratio - 1) * 2))))

def get_expected_goals(att_l, att_c, att_r, def_opp_r, def_opp_c, def_opp_l, possession):
    total_chances = 10.0
    team_chances = total_chances * possession
    eg_c = team_chances * 0.35 * prob_score(att_c / def_opp_c)
    eg_l = team_chances * 0.25 * prob_score(att_l / def_opp_r)
    eg_r = team_chances * 0.25 * prob_score(att_r / def_opp_l)
    eg_sp = team_chances * 0.15 * 0.12
    return eg_c + eg_l + eg_r + eg_sp

def calculate_match_prob(home, away, p45, p90, center_poss=50.0):
    poss_home = (p45 + p90) / 200.0
    if center_poss > 0:
        poss_home = (poss_home * 0.7 + center_poss / 100 * 0.3)
    home_lambda = get_expected_goals(home["att_l"], home["att_c"], home["att_r"],
                                     away["def_r"], away["def_c"], away["def_l"], poss_home)
    away_lambda = get_expected_goals(away["att_l"], away["att_c"], away["att_r"],
                                     home["def_r"], home["def_c"], home["def_l"], 1 - poss_home)
    MAX_G = 10
    h_probs = [poisson_pmf(k, home_lambda) for k in range(MAX_G + 1)]
    a_probs = [poisson_pmf(k, away_lambda) for k in range(MAX_G + 1)]
    win_h = draw = win_a = 0.0
    for h in range(MAX_G + 1):
        for a in range(MAX_G + 1):
            p = h_probs[h] * a_probs[a]
            if h > a: win_h += p
            elif h == a: draw += p
            else: win_a += p
    return round(win_h * 100), round(draw * 100), round(win_a * 100)

# ================== ПАРСИНГ ==================
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

    ratings = re.findall(
        r'(Wretched|Poor|Weak|Inadequate|Passable|Solid|Excellent|Formidable|Outstanding|Brilliant|Magnificent|World Class|Supernatural|Titanic|Extraterrestrial|Mythical|Utopian|Divine|'
        r'Ужасный|Жалкий|Бедный|Слабый|Недостаточный|Приемлемый|Твёрдый|Отличный|Грозный|Выдающийся|Блестящий|Великолепный|Мирового класса|Сверхъестественный|Титанический|Внеземной|Мифический|Утопический|Божественный)'
        r'\s*[-–]?\s*(very low|low|high|very high|очень низкий|низкий|высокий|очень высокий)?',
        text, re.I
    )

    nums = [text_to_rating(f"{lvl} {sub or ''}") for lvl, sub in ratings[:20] if text_to_rating(f"{lvl} {sub or ''}") > 1]

    if len(nums) < 14:
        raise ValueError("Не удалось найти рейтинги игроков (минимум 14).")

    home = {"gk": nums[0], "def_l": nums[1], "def_c": nums[2], "def_r": nums[3],
            "mid": nums[4], "att_l": nums[5], "att_c": nums[6], "att_r": nums[7]}
    away = {"gk": nums[8], "def_l": nums[9], "def_c": nums[10], "def_r": nums[11],
            "mid": nums[12], "att_l": nums[13],
            "att_c": nums[14] if len(nums) > 14 else nums[6],
            "att_r": nums[15] if len(nums) > 15 else nums[7]}
    return home, away, poss45, poss90, center_poss

def parse_match(url: str):
    scraper = cloudscraper.create_scraper()
    r = scraper.get(url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return parse_report_text(soup.get_text())

def process_upload(uploaded_file):
    file_path = f"/tmp/screenshot_{os.urandom(16).hex()}.png"
    uploaded_file.save(file_path)
    try:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="eng+rus")
        return parse_report_text(text)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# ================== HTML (уже вставлен сюда) ==================
MAIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Hattrick Match Analyzer</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; background: #f8f9fa; }
        h1 { color: #28a745; text-align: center; }
        .result { background: #e9f7ef; padding: 25px; border-radius: 12px; margin: 20px 0; border: 2px solid #28a745; font-size: 18px; }
        form { margin: 30px 0; padding: 25px; background: white; border-radius: 8px; box-shadow: 0 2px 15px rgba(0,0,0,0.1); }
        input[type="file"], input[type="text"] { width: 100%; padding: 12px; margin: 10px 0; border: 2px solid #ddd; border-radius: 6px; font-size: 16px; }
        button { padding: 14px 40px; background: #28a745; color: white; border: none; border-radius: 6px; font-size: 18px; cursor: pointer; width: 100%; }
        button:hover { background: #218838; }
        .error { color: #dc3545; background: #f8d7da; padding: 15px; border-radius: 8px; margin: 20px 0; }
    </style>
</head>
<body>
    <h1>🏆 Hattrick Анализатор матча (Render)</h1>
    <p style="text-align:center;">Загружай скриншот отчёта матча — работает через OCR (русский + английский)</p>

    {% if result_html %}
    <div class="result">
        {{ result_html | safe }}
    </div>
    {% endif %}

    {% if error %}
    <div class="error">❌ {{ error }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
        <h2>📸 Загрузить скриншот</h2>
        <input type="file" name="photo" accept="image/*" required>
        <button type="submit">🚀 Анализировать скриншот</button>
    </form>

    <form method="post">
        <h2>🔗 Или ссылка на матч Hattrick</h2>
        <input type="text" name="url" placeholder="https://www.hattrick.org/...MatchID=XXXXXX" style="width:100%;">
        <button type="submit">Анализировать по ссылке</button>
    </form>

    <hr>
    <p><small>Алгоритм 100% идентичен твоему Telegram-боту. Работает на Render.com.</small></p>
</body>
</html>"""

# ================== FLASK ==================
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    result_html = ""
    error = None
    if request.method == 'POST':
        try:
            if 'photo' in request.files and request.files['photo'].filename:
                home, away, p45, p90, center = process_upload(request.files['photo'])
                win_h, draw, win_a = calculate_match_prob(home, away, p45, p90, center)
                result_html = f"""
                <h2>✅ Анализ скриншота завершён!</h2>
                <p><strong>🏠 Победа хозяев:</strong> {win_h}%</p>
                <p><strong>🤝 Ничья:</strong> {draw}%</p>
                <p><strong>🏟️ Победа гостей:</strong> {win_a}%</p>
                <p>Владение 45': {p45}% | 90': {p90}%</p>
                <p>Центр поля: {center}%</p>
                """
            elif 'url' in request.form and request.form['url'].strip():
                url = request.form['url'].strip()
                home, away, p45, p90, center = parse_match(url)
                win_h, draw, win_a = calculate_match_prob(home, away, p45, p90, center)
                result_html = f"""
                <h2>✅ Анализ по ссылке завершён!</h2>
                <p><strong>🏠 Победа хозяев:</strong> {win_h}%</p>
                <p><strong>🤝 Ничья:</strong> {draw}%</p>
                <p><strong>🏟️ Победа гостей:</strong> {win_a}%</p>
                <p>Владение 45': {p45}% | 90': {p90}%</p>
                <p>Центр поля: {center}%</p>
                """
            else:
                error = "Загрузи файл или вставь ссылку!"
        except Exception as e:
            error = f"Ошибка: {str(e)}. Попробуй более чёткий скриншот или проверь ссылку."
    return render_template_string(MAIN_HTML, result_html=result_html, error=error)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
