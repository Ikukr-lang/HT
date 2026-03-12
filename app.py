# ================== app.py (обновлённая версия с фиксом Tesseract) ==================
import math
import os
import re
from flask import Flask, request, render_template_string
from PIL import Image
import pytesseract
import cloudscraper
from bs4 import BeautifulSoup

# === ЯВНЫЙ ПУТЬ К TESSERACT (фиксит ошибку на Render) ===
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# ================== РЕЙТИНГИ ==================
LEVELS_EN = { "disastrous":1,"wretched":2,"poor":3,"weak":4,"inadequate":5,"passable":6,"solid":7,"excellent":8,"formidable":9,"outstanding":10,"brilliant":11,"magnificent":12,"world class":13,"supernatural":14,"titanic":15,"extraterrestrial":16,"mythical":17,"utopian":18,"divine":19 }
LEVELS_RU = { "ужасный":1,"жалкий":2,"бедный":3,"слабый":4,"недостаточный":5,"приемлемый":6,"твёрдый":7,"отличный":8,"грозный":9,"выдающийся":10,"блестящий":11,"великолепный":12,"мирового класса":13,"сверхъестественный":14,"титанический":15,"внеземной":16,"мифический":17,"утопический":18,"божественный":19 }
SUBS_EN = {"very low":0.0,"low":0.25,"high":0.5,"very high":0.75}
SUBS_RU = {"очень низкий":0.0,"низкий":0.25,"высокий":0.5,"очень высокий":0.75}

def text_to_rating(text: str) -> float:
    text = text.lower().strip()
    for lvl_str, val in LEVELS_EN.items():
        if lvl_str in text:
            for s, v in SUBS_EN.items():
                if s in text: return val + v
            return val
    for lvl_str, val in LEVELS_RU.items():
        if lvl_str in text:
            for s, v in SUBS_RU.items():
                if s in text: return val + v
            return val
    return 1.0

# ================== АЛГОРИТМ (без изменений) ==================
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

# ================== ПАРСИНГ ==================
def parse_report_text(text: str):
    poss45 = poss90 = center_poss = 50.0
    m = re.search(r"45['′]?\D*(\d+)%", text, re.I); if m: poss45 = float(m.group(1))
    m = re.search(r"90['′]?\D*(\d+)%", text, re.I); if m: poss90 = float(m.group(1))
    for pat in [r"центр.*?(\d+)%", r"center.*?(\d+)%", r"midfield.*?(\d+)%", r"владения в центре.*?(\d+)%"]:
        m = re.search(pat, text, re.I)
        if m: center_poss = float(m.group(1)); break

    ratings = re.findall(r'(Wretched|Poor|...|Божественный)\s*[-–]?\s*(very low|...|очень высокий)?', text, re.I)  # (полный список как раньше)
    nums = [text_to_rating(f"{lvl} {sub or ''}") for lvl, sub in ratings[:20] if text_to_rating(f"{lvl} {sub or ''}") > 1]

    if len(nums) < 14:
        raise ValueError("Не удалось найти рейтинги игроков (минимум 14).")

    home = {"gk": nums[0],"def_l":nums[1],"def_c":nums[2],"def_r":nums[3],"mid":nums[4],"att_l":nums[5],"att_c":nums[6],"att_r":nums[7]}
    away = {"gk": nums[8],"def_l":nums[9],"def_c":nums[10],"def_r":nums[11],"mid":nums[12],"att_l":nums[13],"att_c":nums[14] if len(nums)>14 else nums[6],"att_r":nums[15] if len(nums)>15 else nums[7]}
    return home, away, poss45, poss90, center_poss

def parse_match(url: str):
    scraper = cloudscraper.create_scraper()
    r = scraper.get(url, timeout=15)
    r.raise_for_status()
    return parse_report_text(BeautifulSoup(r.text, "html.parser").get_text())

def process_upload(uploaded_file):
    file_path = f"/tmp/screenshot_{os.urandom(16).hex()}.png"
    uploaded_file.save(file_path)
    try:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="eng+rus")
        return parse_report_text(text)
    finally:
        os.remove(file_path) if os.path.exists(file_path) else None

# ================== HTML (оставь как есть, или используй свой) ==================
MAIN_HTML = """...твой текущий HTML..."""  # (оставь тот, который уже работает у тебя)

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    result_html = error = None
    if request.method == 'POST':
        try:
            if 'photo' in request.files and request.files['photo'].filename:
                home, away, p45, p90, center = process_upload(request.files['photo'])
                wh, dr, wa = calculate_match_prob(home, away, p45, p90, center)
                result_html = f"<h2>✅ Готово!</h2><p><strong>🏠 Хозяева:</strong> {wh}%</p><p><strong>🤝 Ничья:</strong> {dr}%</p><p><strong>🏟️ Гости:</strong> {wa}%</p><p>Владение: {p45}% / {p90}% | Центр: {center}%</p>"
            # ... (остальная часть обработка ссылки как раньше)
        except Exception as e:
            error = f"Ошибка: {str(e)}"
    return render_template_string(MAIN_HTML, result_html=result_html, error=error)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
