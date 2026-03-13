# ================== app.py (обновлённая версия для нового формата скриншотов) ==================
import math
import os
import re
from flask import Flask, request, render_template_string
from PIL import Image
import pytesseract

# === ФИКС TESSERACT ДЛЯ RENDER ===
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# ================== РЕЙТИНГИ (старый формат — оставлен для совместимости) ==================
LEVELS_EN = {
    "disastrous":1,"wretched":2,"poor":3,"weak":4,"inadequate":5,
    "passable":6,"solid":7,"excellent":8,"formidable":9,"outstanding":10,
    "brilliant":11,"magnificent":12,"world class":13,"supernatural":14,
    "titanic":15,"extraterrestrial":16,"mythical":17,"utopian":18,"divine":19
}
LEVELS_RU = {
    "ужасный":1,"жалкий":2,"бедный":3,"слабый":4,"недостаточный":5,
    "приемлемый":6,"твёрдый":7,"отличный":8,"грозный":9,"выдающийся":10,
    "блестящий":11,"великолепный":12,"мирового класса":13,"сверхъестественный":14,
    "титанический":15,"внеземной":16,"мифический":17,"утопический":18,"божественный":19
}
SUBS_EN = {"very low":0.0,"low":0.25,"high":0.5,"very high":0.75}
SUBS_RU = {"очень низкий":0.0,"низкий":0.25,"высокий":0.5,"очень высокий":0.75}

def text_to_rating(text: str) -> float:
    text = text.lower().strip()
    for lvl, val in LEVELS_EN.items():
        if lvl in text:
            for s, v in SUBS_EN.items():
                if s in text: return val + v
            return val
    for lvl, val in LEVELS_RU.items():
        if lvl in text:
            for s, v in SUBS_RU.items():
                if s in text: return val + v
            return val
    return 1.0

# ================== АЛГОРИТМ РАСЧЁТА (оставлен БЕЗ ИЗМЕНЕНИЙ) ==================
def poisson_pmf(k: int, lam: float) -> float:
    if lam == 0: return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def prob_score(ratio: float) -> float:
    return max(0.05, min(0.45, 0.05 + 0.35 / (1 + math.exp(-(ratio - 1) * 2))))

def get_expected_goals(att_l, att_c, att_r, def_opp_r, def_opp_c, def_opp_l, possession):
    total = 10.0
    ch = total * possession
    return (ch*0.35*prob_score(att_c/def_opp_c) +
            ch*0.25*prob_score(att_l/def_opp_r) +
            ch*0.25*prob_score(att_r/def_opp_l) +
            ch*0.15*0.12)

def calculate_match_prob(home, away, p45, p90, center_poss=50.0):
    poss_home = (p45 + p90)/200
    if center_poss > 0: poss_home = poss_home*0.7 + center_poss/100*0.3
    hl = get_expected_goals(home["att_l"],home["att_c"],home["att_r"], away["def_r"],away["def_c"],away["def_l"], poss_home)
    al = get_expected_goals(away["att_l"],away["att_c"],away["att_r"], home["def_r"],home["def_c"],home["def_l"], 1-poss_home)
    MAX_G = 10
    hp = [poisson_pmf(k, hl) for k in range(MAX_G+1)]
    ap = [poisson_pmf(k, al) for k in range(MAX_G+1)]
    wh = dr = wa = 0.0
    for h in range(MAX_G+1):
        for a in range(MAX_G+1):
            p = hp[h]*ap[a]
            if h > a: wh += p
            elif h == a: dr += p
            else: wa += p
    return round(wh*100), round(dr*100), round(wa*100)

# ================== ПАРСИНГ (обновлён для нового формата скриншотов) ==================
def parse_report_text(text: str):
    # === 1. ВЛАДЕНИЕ ИЗ ГРАФИКА ПОЛЯ (новый формат — берём все зоны с 0 минуты) ===
    poss45 = poss90 = center_poss = 50.0
    zone_percents = re.findall(r'(\d+)%', text)
    if len(zone_percents) >= 14:  # 7 зон × 2 команды (home/away чередуются)
        home_zones = [int(x) for x in zone_percents[0::2][:7]]
        p45 = p90 = round(sum(home_zones) / len(home_zones))
        center_poss = home_zones[3] if len(home_zones) > 3 else p45  # 4-я зона = центр
    else:
        # старый fallback (если скриншот старого формата)
        m = re.search(r"45['′]?\D*(\d+)%", text, re.I)
        if m: poss45 = float(m.group(1))
        m = re.search(r"90['′]?\D*(\d+)%", text, re.I)
        if m: poss90 = float(m.group(1))
        for pat in [r"центр.*?(\d+)%", r"center.*?(\d+)%", r"midfield.*?(\d+)%", r"владения в центре.*?(\d+)%"]:
            m = re.search(pat, text, re.I)
            if m: center_poss = float(m.group(1)); break
        p45 = poss45
        p90 = poss90

    # === 2. РЕЙТИНГИ ИГРОКОВ (новый формат — 14 числовых значений из «Подробные рейтинги») ===
    section_match = re.search(r'(?s)Подробные рейтинги(.*?)Свободные удары', text, re.I)
    if section_match:
        section_text = section_match.group(1)
        rating_strs = re.findall(r'(\d+[.,]\d{2})', section_text)
        if len(rating_strs) >= 14:
            nums = [float(x.replace(',', '.')) for x in rating_strs[:14]]
            # маппинг по порядку строк (mid, def_r, def_c, def_l, att_r, att_c, att_l)
            home = {
                "gk": 5.0,          # не используется
                "def_l": nums[6],
                "def_c": nums[4],
                "def_r": nums[2],
                "mid": nums[0],
                "att_l": nums[12],
                "att_c": nums[10],
                "att_r": nums[8]
            }
            away = {
                "gk": 5.0,
                "def_l": nums[7],
                "def_c": nums[5],
                "def_r": nums[3],
                "mid": nums[1],
                "att_l": nums[13],
                "att_c": nums[11],
                "att_r": nums[9]
            }
            return home, away, float(p45), float(p90), float(center_poss)

    # === 3. Fallback на старый парсинг по словам (для очень старых скриншотов) ===
    ratings = re.findall(
        r'(Wretched|Poor|Weak|Inadequate|Passable|Solid|Excellent|Formidable|Outstanding|Brilliant|Magnificent|World Class|Supernatural|Titanic|Extraterrestrial|Mythical|Utopian|Divine|'
        r'Ужасный|Жалкий|Бедный|Слабый|Недостаточный|Приемлемый|Твёрдый|Отличный|Грозный|Выдающийся|Блестящий|Великолепный|Мирового класса|Сверхъестественный|Титанический|Внеземной|Мифический|Утопический|Божественный)'
        r'\s*[-–]?\s*(very low|low|high|very high|очень низкий|низкий|высокий|очень высокий)?',
        text, re.I
    )
    nums = [text_to_rating(f"{lvl} {sub or ''}") for lvl, sub in ratings[:20] if text_to_rating(f"{lvl} {sub or ''}") > 1]

    if len(nums) < 14:
        raise ValueError("Не удалось найти рейтинги игроков (минимум 14).")

    home = {"gk": nums[0],"def_l":nums[1],"def_c":nums[2],"def_r":nums[3],"mid":nums[4],"att_l":nums[5],"att_c":nums[6],"att_r":nums[7]}
    away = {"gk": nums[8],"def_l":nums[9],"def_c":nums[10],"def_r":nums[11],"mid":nums[12],"att_l":nums[13],
            "att_c": nums[14] if len(nums)>14 else nums[6],
            "att_r": nums[15] if len(nums)>15 else nums[7]}
    return home, away, float(p45), float(p90), float(center_poss)

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

# ================== HTML (без изменений) ==================
MAIN_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Hattrick Анализатор</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background: #f8f9fa; }
        h1 { color: #28a745; text-align: center; }
        .result { background: #e9f7ef; padding: 25px; border-radius: 12px; margin: 20px 0; border: 2px solid #28a745; font-size: 18px; }
        form { margin: 30px 0; padding: 25px; background: white; border-radius: 8px; box-shadow: 0 2px 15px rgba(0,0,0,0.1); }
        input[type="file"] { width: 100%; padding: 12px; margin: 10px 0; border: 2px solid #ddd; border-radius: 6px; font-size: 16px; }
        button { padding: 14px 40px; background: #28a745; color: white; border: none; border-radius: 6px; font-size: 18px; cursor: pointer; width: 100%; }
        button:hover { background: #218838; }
        .error { color: #dc3545; background: #f8d7da; padding: 15px; border-radius: 8px; margin: 20px 0; }
    </style>
</head>
<body>
    <h1>🏆 Hattrick Анализатор матча</h1>
    <p style="text-align:center;">Загружай скриншот отчёта матча — работает через OCR (новый + старый формат)</p>

    {% if result_html %}
    <div class="result">{{ result_html | safe }}</div>
    {% endif %}

    {% if error %}
    <div class="error">❌ {{ error }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
        <h2>📸 Загрузить скриншот</h2>
        <input type="file" name="photo" accept="image/*" required>
        <button type="submit">🚀 Анализировать скриншот</button>
    </form>

    <hr>
    <p><small>Алгоритм расчёта полностью как раньше. Теперь берёт цифры рейтингов и владение из графика поля.</small></p>
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
                <h2>✅ Анализ завершён!</h2>
                <p><strong>🏠 Победа хозяев:</strong> {win_h}%</p>
                <p><strong>🤝 Ничья:</strong> {draw}%</p>
                <p><strong>🏟️ Победа гостей:</strong> {win_a}%</p>
                <p>Владение 45': {p45}% | 90': {p90}%</p>
                <p>Центр поля: {center}%</p>
                """
            else:
                error = "Загрузи скриншот!"
        except Exception as e:
            error = f"Ошибка: {str(e)}. Попробуй более чёткий скриншот."
    return render_template_string(MAIN_HTML, result_html=result_html, error=error)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
