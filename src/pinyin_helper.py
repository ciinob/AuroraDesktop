"""Zero-dependency Chinese Pinyin initials & fuzzy matching engine (GB2312 boundary + common overrides)."""

# Common characters outside GB2312 Level-1 or polyphonic app names
CHAR_INITIAL_OVERRIDES = {
    "夸": "k", "哔": "b", "哩": "l", "钉": "d", "讯": "x", "腾": "t",
    "微": "w", "信": "x", "网": "w", "易": "y", "云": "y", "音": "y", "乐": "l",
    "剪": "j", "映": "y", "火": "h", "绒": "r", "图": "t", "吧": "b",
    "外": "w", "星": "x", "仔": "z", "完": "w", "美": "m", "暴": "b", "雪": "x",
    "短": "d", "剧": "j", "数": "s", "学": "x", "文": "w", "献": "x", "重": "c",
    "调": "t", "行": "x", "长": "c", "藏": "c", "厦": "x", "翟": "z",
}

# GB2312 Level-1 Pinyin boundary table (big-endian uint16 codepoints)
GB2312_BOUNDARIES = [
    (0xB0A1, 0xB0C4, "a"),
    (0xB0C5, 0xB2C0, "b"),
    (0xB2C1, 0xB4ED, "c"),
    (0xB4EE, 0xB6E9, "d"),
    (0xB6EA, 0xB7A1, "e"),
    (0xB7A2, 0xB8C0, "f"),
    (0xB8C1, 0xB9FD, "g"),
    (0xB9FE, 0xBBF6, "h"),
    (0xBBF7, 0xBFA5, "j"),
    (0xBFA6, 0xC0AB, "k"),
    (0xC0AC, 0xC2E7, "l"),
    (0xC2E8, 0xC4C2, "m"),
    (0xC4C3, 0xC5B5, "n"),
    (0xC5B6, 0xC5BD, "o"),
    (0xC5BE, 0xC6D9, "p"),
    (0xC6DA, 0xC8BA, "q"),
    (0xC8BB, 0xC8F5, "r"),
    (0xC8F6, 0xCBF9, "s"),
    (0xCBFA, 0xCDD9, "t"),
    (0xCDDA, 0xCEF3, "w"),
    (0xCEF4, 0xD1B8, "x"),
    (0xD1B9, 0xD4D0, "y"),
    (0xD4D1, 0xD7F9, "z"),
]


def char_to_initial(ch: str) -> str:
    if ch in CHAR_INITIAL_OVERRIDES:
        return CHAR_INITIAL_OVERRIDES[ch]
    if ord(ch) < 128:
        return ch.lower()
    try:
        raw = ch.encode("gb2312")
        if len(raw) == 2:
            code = (raw[0] << 8) | raw[1]
            for low, high, letter in GB2312_BOUNDARIES:
                if low <= code <= high:
                    return letter
    except UnicodeEncodeError:
        pass
    return ""


def get_pinyin_initials(text: str) -> str:
    """Convert '网易云音乐' -> 'wyyyy', 'VS Code' -> 'vscode'."""
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(char_to_initial(ch))
    return "".join(out)


def fuzzy_match_score(query: str, title: str, subtitle: str = "") -> int:
    """Return match relevance score (>0 matches, 0 no match). Supports substring, initials, and subsequence."""
    q = query.strip().lower().replace(" ", "")
    if not q:
        return 1

    t_low = title.lower()
    t_compact = t_low.replace(" ", "")
    initials = get_pinyin_initials(title)
    sub_low = subtitle.lower()

    # 1. Exact prefix match on title or pinyin initials -> highest priority
    if t_compact.startswith(q):
        return 1000 - len(t_compact)
    if initials.startswith(q):
        return 920 - len(initials)

    # 2. Word-boundary or substring match in title
    if q in t_compact:
        idx = t_compact.find(q)
        return 820 - idx * 10 - len(t_compact)
    if q in initials:
        idx = initials.find(q)
        return 760 - idx * 10

    # 3. Fuzzy subsequence match on title or initials (e.g. 'vsc' -> 'VS Code', 'clv' -> 'Clash Verge')
    qi = 0
    gaps = 0
    for ch in t_compact:
        if qi < len(q) and ch == q[qi]:
            qi += 1
        elif qi > 0:
            gaps += 1
    if qi == len(q):
        return max(400, 650 - gaps * 12)

    qi = 0
    for ch in initials:
        if qi < len(q) and ch == q[qi]:
            qi += 1
    if qi == len(q):
        return 520

    # 4. Subtitle / group / path match
    if q in sub_low:
        return 300

    return 0
