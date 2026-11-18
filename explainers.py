"""
explainers.py — evergreen "60-second lesson" reels that teach a betting skill and plug Edgelytics IQ.

Scripts are hand-written so every number is exact (the on-screen math is computed by render.py from
the odds below). Each topic has a few hook variants so repeats don't look identical.
Add a topic: copy one block, give it a new id. The bot rotates topics least-recently-used first.
"""
import random

from config import DISCLAIMER, HANDLE

TAG = "EDGELYTICS IQ · 60-SECOND LESSON"
FOLLOW = f"Follow {HANDLE} — we scan the books every day so you don't have to."

TOPICS = {
    "arb": {
        "title": "Arbitrage in 60 seconds",
        "hooks": [
            ("Two sportsbooks can disagree so much you profit no matter who wins. Here's arbitrage in sixty seconds.",
             "PROFIT EITHER WAY?", "EITHER"),
            ("This is the only bet where you win no matter who wins. It's called arbitrage.",
             "WIN NO MATTER WHAT?", "WIN"),
        ],
        "scenes": [
            {"type": "calc", "mode": "arb", "odds": [110, 105], "names": ["Book A · Team A", "Book B · Team B"],
             "label": "Step 1: implied odds",
             "vo": "One book has Team A at plus one-ten. Another has Team B at plus one-oh-five. Convert both to "
                   "implied probability: forty-seven point six, and forty-eight point eight percent. Together, under one hundred."},
            {"type": "calc", "mode": "stakes", "odds": [110, 105], "names": ["Book A · Team A", "Book B · Team B"],
             "total": 1000, "label": "Step 2: split the stake",
             "vo": "Split a thousand dollars in that same ratio. Four ninety-four on A, five-oh-six on B. "
                   "Either side pays about ten thirty-seven. Thirty-seven dollars profit, either way."},
            {"type": "point", "eyebrow": "THE CATCH", "text": "GAPS CLOSE IN SECONDS",
             "vo": "The catch: these gaps close fast, and books limit accounts that only bet arbs. You need speed and money at several books."},
            {"type": "cta", "text": "WE SCAN THE BOOKS",
             "vo": "Edgelytics IQ scans the books for gaps like this. Follow so you catch the next one."},
        ],
        "caption": "Arbitrage in 60 seconds 🧮\nTwo books disagree → you bet both sides → profit either way.\nThe math is simple. The speed is the hard part.\nWould you try it? 👇",
        "hashtags": ["arbitrage", "sportsbetting", "arbbetting", "bettingtips", "lineshopping", "edgelyticsiq", "bettingmath"],
        "broll": "stock market screens",
    },
    "lineshop": {
        "title": "How to line shop",
        "hooks": [
            ("You're paying too much for the exact same bet. Here's how to line shop.", "SAME BET. BETTER PRICE.", "BETTER"),
            ("Betting at one sportsbook is like buying gas at the first station you see.", "STOP USING ONE BOOK", "ONE"),
        ],
        "scenes": [
            {"type": "shop", "label": "Same bet, 4 books", "title": "Chiefs spread",
             "rows": [["DraftKings", "-7.5", "-110"], ["FanDuel", "-7", "-110"], ["BetMGM", "-7.5", "-105"], ["Caesars", "-7", "-115"]],
             "best": 1,
             "vo": "Same game, four books. One hangs minus seven and a half, another just minus seven. That half point decides more bets than you'd think."},
            {"type": "point", "eyebrow": "STEP 1", "text": "OPEN 3+ SPORTSBOOKS",
             "vo": "Step one: have accounts at three or more books."},
            {"type": "point", "eyebrow": "STEP 2", "text": "CHECK EVERY BOOK FIRST",
             "vo": "Step two: before every bet, check them all. Best number first, then best price."},
            {"type": "calc", "mode": "odds", "odds": [-110, -105], "names": ["Standard price", "Shopped price"],
             "label": "Why price matters", "verdict": "LOWER JUICE = LOWER BAR",
             "sub": "BREAK-EVEN 52.38% → 51.22%",
             "vo": "At minus one-ten you need to win fifty-two point four percent to break even. At minus one-oh-five, fifty-one point two."},
            {"type": "cta", "text": "WE COMPARE THE BOOKS",
             "vo": "Edgelytics IQ compares the books for you every day. Follow for the best numbers."},
        ],
        "caption": "How to line shop in 60 seconds 🛒\nSame bet. Different books. Different prices.\nHalf a point and a few cents of juice add up over a season.\nHow many books do you use? 👇",
        "hashtags": ["lineshopping", "sportsbetting", "bettingtips", "sharpbetting", "edgelyticsiq", "sportsbook", "bettingstrategy"],
        "broll": "stadium crowd night",
    },
    "vig": {
        "title": "What the vig costs you",
        "hooks": [
            ("Every bet you make has a hidden fee. It's called the vig.", "THE HIDDEN FEE", "HIDDEN"),
            ("Why do both sides cost minus one-ten? Because the book takes a cut.", "WHY BOTH SIDES ARE -110", "-110"),
        ],
        "scenes": [
            {"type": "calc", "mode": "vig", "odds": [-110, -110], "names": ["Side A", "Side B"], "label": "Both sides at -110",
             "vo": "Minus one-ten on both sides means each side implies fifty-two point four percent. Add them up: one oh four point eight. "
                   "That extra is the book's cut, about four and a half percent."},
            {"type": "point", "eyebrow": "BREAK EVEN", "text": "YOU NEED 52.4%",
             "vo": "So at minus one-ten, you have to win fifty-two point four percent of your bets just to break even."},
            {"type": "point", "eyebrow": "THE FIX", "text": "SHOP FOR LOWER JUICE",
             "vo": "The fix: shop for minus one-oh-five or better. Lower juice means a lower bar to profit."},
            {"type": "cta", "text": "STOP OVERPAYING",
             "vo": "Edgelytics IQ shows you where the juice is lowest. Follow for more."},
        ],
        "caption": "The vig, explained 💸\n-110 on both sides = the book keeps ~4.5%.\nYou need 52.4% just to break even.\nDid you know this? 👇",
        "hashtags": ["vig", "juice", "sportsbetting", "bettingtips", "bettingmath", "edgelyticsiq", "sportsbook"],
        "broll": "casino chips table",
    },
    "clv": {
        "title": "Closing line value",
        "hooks": [
            ("The best sign you're a sharp bettor isn't winning. It's beating the closing line.", "BEAT THE CLOSE", "CLOSE"),
            ("Pros don't judge a bet by whether it won. They judge it by this.", "HOW PROS GRADE BETS", "PROS"),
        ],
        "game": {"league": "NFL", "spread_open": -3.0, "spread_now": -4.5, "spread_text": "BET -4.5"},
        "scenes": [
            {"type": "number", "label": "You bet -3. It closed -4.5",
             "vo": "Say you bet a team at minus three. By kickoff the line closes at minus four and a half. "
                   "You got a better number than the market's final price. That's closing line value."},
            {"type": "point", "eyebrow": "WHY IT MATTERS", "text": "THE CLOSE IS THE SHARPEST LINE",
             "vo": "The closing line has the most information baked in. Beating it consistently is the best predictor of long-term profit."},
            {"type": "point", "eyebrow": "HOW", "text": "BET EARLY, SHOP EVERY BOOK",
             "vo": "How to get it: bet before the market moves, and always shop for the best number."},
            {"type": "cta", "text": "TRACK YOUR CLV",
             "vo": "Edgelytics IQ tracks line movement for you. Follow for daily edges."},
        ],
        "caption": "Closing line value (CLV), explained 📈\nWinning one bet is luck. Beating the close over and over is skill.\nDo you track your CLV? 👇",
        "hashtags": ["clv", "closinglinevalue", "sharpbetting", "sportsbetting", "bettingtips", "edgelyticsiq", "linemovement"],
        "broll": "american football stadium",
    },
    "keynums": {
        "title": "NFL key numbers",
        "hooks": [
            ("Why is minus two and a half so different from minus three? Key numbers.", "-2.5 VS -3", "-3"),
            ("Not every half point is equal in the NFL. Here's why.", "NOT ALL HALF POINTS", "HALF"),
        ],
        "game": {"league": "NFL", "spread": -3.5, "spread_text": "FAV -3.5"},
        "scenes": [
            {"type": "number", "label": "Why -3 matters",
             "vo": "Football scores come in threes and sevens, so more NFL games land on a three point margin than any other. Seven is next."},
            {"type": "point", "eyebrow": "WHAT IT MEANS", "text": "-2.5 AND -3.5 ARE WORLDS APART",
             "vo": "That's why minus two and a half and minus three and a half are worlds apart. One wins on a three point game, the other loses."},
            {"type": "point", "eyebrow": "THE MOVE", "text": "PAY UP FOR 3 AND 7",
             "vo": "If you can get to the right side of three or seven, it's often worth paying a little extra juice."},
            {"type": "cta", "text": "KNOW THE NUMBERS",
             "vo": "Edgelytics IQ flags when a line crosses a key number. Follow for more."},
        ],
        "caption": "NFL key numbers 🏈\n3 and 7 are the most common margins — so -2.5 and -3.5 are NOT the same bet.\nWhich side of 3 do you want? 👇",
        "hashtags": ["nflbetting", "keynumbers", "sportsbetting", "nfl", "bettingtips", "edgelyticsiq", "spread"],
        "broll": "american football field",
    },
    "readodds": {
        "title": "How to read betting odds",
        "hooks": [
            ("Plus one-fifty, minus one-fifty. Here's what those numbers actually mean.", "WHAT +150 MEANS", "+150"),
            ("If betting odds confuse you, this takes thirty seconds.", "ODDS IN 30 SECONDS", "30"),
        ],
        "scenes": [
            {"type": "calc", "mode": "odds", "odds": [150, -150], "names": ["Underdog", "Favorite"], "label": "American odds",
             "vo": "Plus one-fifty: bet a hundred to win one-fifty. Minus one-fifty: bet one-fifty to win a hundred. "
                   "Plus is the underdog, minus is the favorite."},
            {"type": "point", "eyebrow": "THE TRICK", "text": "ODDS = PROBABILITY",
             "vo": "Every price is really a probability. Plus one-fifty implies forty percent. Minus one-fifty implies sixty."},
            {"type": "point", "eyebrow": "THE EDGE", "text": "BET WHEN YOU DISAGREE",
             "vo": "You only have an edge when you think the real chance is higher than the price implies."},
            {"type": "cta", "text": "LEARN THE MATH",
             "vo": "Edgelytics IQ breaks down the math behind every line. Follow to learn more."},
        ],
        "caption": "How to read betting odds 🔢\n+150 → bet $100 to win $150 (40% implied)\n-150 → bet $150 to win $100 (60% implied)\nSave this for later 📌",
        "hashtags": ["bettingodds", "sportsbetting", "bettingforbeginners", "bettingtips", "edgelyticsiq", "oddsexplained"],
        "broll": "basketball arena crowd",
    },
}


def pick_topic(state, forced=""):
    """Forced topic if valid, else the least recently used one."""
    if forced in TOPICS:
        return forced
    last = {}
    for i, p in enumerate(state.get("posts", [])):
        if p.get("kind") == "explainer" and p.get("topic"):
            last[p["topic"]] = i
    order = list(TOPICS)
    random.shuffle(order)
    return min(order, key=lambda k: last.get(k, -1))


def build_script(topic_id, state):
    t = TOPICS[topic_id]
    used = [p.get("hook") for p in state.get("posts", [])]
    hooks = [h for h in t["hooks"] if h[1] not in used] or t["hooks"]
    vo, text, accent = random.choice(hooks)
    scenes = [{"type": "hook", "vo": vo, "text": text, "accent": accent, "tag": TAG}] + [dict(s) for s in t["scenes"]]
    tags = " ".join("#" + h for h in t["hashtags"])
    script = {
        "kind": "explainer", "topic": topic_id, "scenes": scenes,
        "caption": t["caption"], "hashtags": t["hashtags"],
        "music_mood": "confident hype trap", "broll_query": t["broll"],
        "full_caption": f"{t['caption']}\n\n{FOLLOW}\n\n{DISCLAIMER}\n\n{tags}",
    }
    game = dict(t.get("game") or {}, id=f"explainer-{topic_id}")
    return script, game
