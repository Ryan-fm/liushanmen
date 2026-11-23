"""Answer F1 race-winner questions from the official season results table."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener

from .memory import phrase_pattern, searchable_text
from .sources import CST, NoRedirect, now

OFFICIAL = "https://www.formula1.com"
RESULT_PATH = re.compile(r"/en/results/(\d{4})/races/\d+/([a-z0-9-]+)/race-result")
CHAMPION = re.compile(r"冠军|冠軍|谁赢|誰贏|谁夺冠|誰奪冠|正赛结果|正賽結果|赛果|賽果|"
                      r"\b(?:who won|who is the winner|race winner|race results?)\b", re.I)
MONITOR = re.compile(r"监测|監測|跟踪|跟蹤|关注|關注|提醒|\b(?:track|monitor|follow|alert me)\b", re.I)
OTHER_EVENT = re.compile(r"冲刺|衝刺|排位|杆位|桿位|练习赛|練習賽|赛季冠军|賽季冠軍|"
                         r"世界冠军|世界冠軍|车队冠军|車隊冠軍|"
                         r"\b(?:sprint|qualifying|pole|practice|F2|F3|F1 Academy|IndyCar|NASCAR)\b", re.I)
NEWS = re.compile(r"新闻|新聞|报道|報道|资讯|資訊|\bnews\b", re.I)
QUESTION = re.compile(r"谁|誰|哪位|\bwho\b|[？?]", re.I)
YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
RACE_TIME = re.compile(r"(?:\d+:)?\d{1,2}:\d{2}(?:\.\d+)?")

VENUES = {
    "las-vegas": ("Las Vegas", "拉斯维加斯站", ("拉斯维加斯", "拉斯維加斯", "阿斯维加斯", "阿斯維加斯", "Vegas")),
    "china": ("China", "中国站", ("中国站", "中國站", "中国大奖赛", "中國大獎賽", "上海站", "Shanghai")),
    "japan": ("Japan", "日本站", ("日本站", "日本大奖赛", "日本大獎賽", "铃鹿", "鈴鹿", "Suzuka")),
    "australia": ("Australia", "澳大利亚站", ("澳大利亚站", "澳洲站", "墨尔本", "Melbourne", "Australian")),
    "miami": ("Miami", "迈阿密站", ("迈阿密", "邁阿密")),
    "canada": ("Canada", "加拿大站", ("加拿大站", "加拿大大奖赛", "蒙特利尔", "Montreal", "Canadian")),
    "monaco": ("Monaco", "摩纳哥站", ("摩纳哥", "摩納哥")),
    "barcelona-catalunya": ("Barcelona-Catalunya", "巴塞罗那站", ("巴塞罗那", "巴塞羅那", "Barcelona")),
    "spain": ("Spain", "西班牙站", ("西班牙站", "西班牙大奖赛", "马德里站", "Madrid", "Spanish")),
    "austria": ("Austria", "奥地利站", ("奥地利站", "奧地利站", "红牛环", "Red Bull Ring", "Austrian")),
    "great-britain": ("Great Britain", "英国站", ("英国站", "英國站", "英国大奖赛", "银石", "銀石", "Silverstone", "British")),
    "belgium": ("Belgium", "比利时站", ("比利时站", "比利時站", "斯帕", "Spa-Francorchamps", "Belgian")),
    "hungary": ("Hungary", "匈牙利站", ("匈牙利站", "亨格罗林", "Hungaroring", "Hungarian")),
    "netherlands": ("Netherlands", "荷兰站", ("荷兰站", "荷蘭站", "赞德沃特", "Zandvoort", "Dutch")),
    "italy": ("Italy", "意大利站", ("意大利站", "義大利站", "蒙扎", "Monza", "Italian")),
    "azerbaijan": ("Azerbaijan", "阿塞拜疆站", ("阿塞拜疆", "巴库站", "Baku")),
    "bahrain": ("Bahrain", "巴林大奖赛", ("巴林", "Sakhir")),
    "singapore": ("Singapore", "新加坡站", ("新加坡", "滨海湾", "Marina Bay")),
    "united-states": ("United States", "美国站", ("美国站", "美國站", "美国大奖赛", "奥斯汀", "Austin", "US Grand Prix")),
    "mexico": ("Mexico", "墨西哥站", ("墨西哥", "Mexico City", "Mexican")),
    "brazil": ("Brazil", "圣保罗站", ("巴西站", "巴西大奖赛", "圣保罗", "聖保羅", "São Paulo", "Sao Paulo", "Brazilian")),
    "qatar": ("Qatar", "卡塔尔站", ("卡塔尔", "卡達", "Lusail")),
    "abu-dhabi": ("Abu Dhabi", "阿布扎比站", ("阿布扎比", "亚斯码头", "Yas Marina")),
    "saudi-arabia": ("Saudi Arabia", "沙特阿拉伯站", ("沙特", "吉达", "Jeddah")),
    "emilia-romagna": ("Emilia-Romagna", "艾米利亚-罗马涅站", ("伊莫拉", "Imola", "艾米利亚罗马涅")),
}
DRIVERS_ZH = {
    "Max Verstappen": "马克斯·维斯塔潘", "Lando Norris": "兰多·诺里斯", "Oscar Piastri": "奥斯卡·皮亚斯特里",
    "George Russell": "乔治·拉塞尔", "Kimi Antonelli": "基米·安东内利",
    "Charles Leclerc": "夏尔·勒克莱尔", "Lewis Hamilton": "刘易斯·汉密尔顿",
    "Carlos Sainz": "卡洛斯·塞恩斯", "Sergio Perez": "塞尔吉奥·佩雷兹",
    "Daniel Ricciardo": "丹尼尔·里卡多", "Sebastian Vettel": "塞巴斯蒂安·维特尔",
    "Fernando Alonso": "费尔南多·阿隆索", "Valtteri Bottas": "瓦尔特里·博塔斯",
}
TEAMS_ZH = {
    "Red Bull Racing": "红牛车队", "McLaren": "迈凯伦车队", "Mercedes": "梅赛德斯车队",
    "Ferrari": "法拉利车队", "Williams": "威廉姆斯车队", "Aston Martin": "阿斯顿·马丁车队",
}
VENUE_PATTERNS = {slug: [phrase_pattern(alias) for alias in (english, chinese, *aliases)]
                  for slug, (english, chinese, aliases) in VENUES.items()}


def race_question(intent):
    text = searchable_text(intent)
    if not CHAMPION.search(text) or MONITOR.search(text) or OTHER_EVENT.search(text):
        return None
    if NEWS.search(text) and not QUESTION.search(text):
        return None
    venues = [slug for slug, patterns in VENUE_PATTERNS.items() if any(pattern.search(text) for pattern in patterns)]
    years = set(YEAR.findall(text))
    if len(venues) != 1 or len(years) > 1:
        return None
    current = now().astimezone(CST).year
    if years:
        seasons = (int(years.pop()),)
    elif re.search(r"去年|上赛季|上賽季|\blast (?:year|season)\b", text):
        seasons = (current - 1,)
    elif re.search(r"今年|本赛季|本賽季|\bthis (?:year|season)\b", text):
        seasons = (current,)
    else:
        seasons = (current, current - 1)
    return venues[0], seasons


class SeasonTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.header = False
        self.cells = None
        self.cell = None
        self.links = []
        self.svg_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "svg":
            self.svg_depth += 1
        if self.svg_depth:
            return
        if tag == "tr":
            self.cells, self.cell, self.links = [], None, []
        elif self.cells is not None and tag in ("td", "th"):
            self.cell = []
        elif self.cell is not None and not self.cells and tag == "a":
            self.links.append(dict(attrs).get("href", ""))

    def handle_endtag(self, tag):
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
            return
        if self.svg_depth:
            return
        if self.cell is not None and tag in ("td", "th"):
            self.cells.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif self.cells is not None and tag == "tr":
            if self.cells[:6] == ["Grand Prix", "Date", "Winner", "Team", "Laps", "Time"]:
                self.header = True
            if self.links:
                self.rows.append((self.cells, self.links))
            self.cells, self.cell = None, None

    def handle_data(self, data):
        if self.cell is not None and not self.svg_depth:
            self.cell.append(data)


def season_results(season):
    url = f"{OFFICIAL}/en/results/{season}/races"
    request = Request(url, headers={"User-Agent": "Liushanmen/1.0", "Accept": "text/html"})
    with build_opener(NoRedirect).open(request, timeout=8) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("Official season result page is too large")
    return parse_season(payload.decode("utf-8"), season)


def parse_season(html, season):
    table = SeasonTable()
    table.feed(html)
    table.close()
    if not table.header:
        raise ValueError("Official result table not found")

    results = {}
    for cells, links in table.rows:
        if len(cells) < 6:
            continue
        _, day, driver, team, laps, time = cells[:6]
        if not (driver and team and laps.isdecimal() and RACE_TIME.fullmatch(time)):
            continue
        for href in links:
            parsed = urlsplit(urljoin(OFFICIAL, href))
            match = RESULT_PATH.fullmatch(parsed.path)
            if parsed.scheme != "https" or parsed.netloc != "www.formula1.com" or not match or int(match[1]) != season:
                continue
            # The official table appends a three-letter driver code to the display name.
            driver = re.sub(r"\s+[A-Z]{3}$", "", driver)
            results[match[2]] = {"season": season, "driver": driver, "driver_zh": DRIVERS_ZH.get(driver, ""),
                                 "team": team, "team_zh": TEAMS_ZH.get(team, ""), "day": day,
                                 "laps": int(laps), "time": time, "url": OFFICIAL + parsed.path}
            break
    return results


def lookup_winner(question):
    slug, seasons = question
    english, chinese, _ = VENUES[slug]
    race = {"race": english, "race_zh": chinese}
    current = now().astimezone(CST).year
    fallback = f"{OFFICIAL}/en/results/{min(max(seasons[0], 1950), current)}/races"
    for season in seasons:
        if not 1950 <= season <= current:
            continue
        try:
            result = season_results(season).get(slug)
        except (OSError, ValueError):
            return {**race, "status": "unavailable", "url": fallback}
        if result:
            return {**race, **result, "status": "found"}
    return {**race, "season": seasons[0], "status": "not_found", "url": fallback}
