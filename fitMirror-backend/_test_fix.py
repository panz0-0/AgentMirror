_COMMON_CJK = set(
    "的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感"
    "介绍绍运运动卫衣闲简裙裤包包鞋帽上装下装外套衬衫T恤价格钱尺码大小号颜色红白黑蓝绿灰紫粉黄棕吗呢吧啊呀哦啦今雨雪风火水山"
)

_NORMAL_CHARS = _COMMON_CJK | set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " ,.!;:，。！？；：、""''（）()[]{}【】《》<>/\\-—…·\n\t"
)

_GARBLE_MARKERS = set("浠嬬粛涓€銆佸鍙堢瓑涓嬮洦鍚")

_COMMON_BIGRAMS = {
    "介绍", "一下", "今天", "下雨", "运动", "休闲", "卫衣", "简约", "黑色",
    "吊带", "带裙", "价格", "多少", "这件", "裙子", "商品", "哪些", "什么",
    "可以", "没有", "我们", "你们", "他们", "这个", "那个", "怎么", "为什么",
    "试试", "效果", "搭配", "建议", "尺码", "合适", "喜欢", "看看", "推荐",
    "好吗", "雨吗", "对吗", "是吗", "有吗", "在吗",
}


def has_garble_marker(text):
    return any(c in _GARBLE_MARKERS for c in text)


def is_normal_char(c):
    if c in ('?', '€'):
        return False
    return c in _NORMAL_CHARS


def score(text):
    if not text:
        return 0
    common = sum(1 for c in text if c in _COMMON_CJK)
    bigrams = sum(1 for i in range(len(text) - 1) if text[i:i+2] in _COMMON_BIGRAMS)
    return common / len(text) + bigrams * 0.5


def fix_segment(seg):
    if not seg:
        return seg
    seg = seg.replace('€', '\x80')
    encoded = bytearray()
    for c in seg:
        if c == '\x80':
            encoded.append(0x80)
        else:
            try:
                encoded.extend(c.encode('gbk'))
            except Exception:
                encoded.extend(c.encode('gbk', errors='replace'))
    try:
        result = bytes(encoded).decode('utf-8')
        if score(result) > score(seg):
            return result
    except Exception:
        pass
    if b'?' in encoded:
        best = None
        best_score = -1
        for b in range(0x00, 0xFF):
            test = bytes(encoded).replace(b'?', bytes([b]))
            try:
                result = test.decode('utf-8')
                s = score(result)
                if s > best_score:
                    best_score = s
                    best = result
            except Exception:
                continue
        if best is not None and best_score > score(seg):
            return best
    return seg


def fix_gbk_garbled(text):
    if not text:
        return text
    if not has_garble_marker(text):
        return text
    result = []
    buf = []
    for c in text:
        if is_normal_char(c):
            if buf:
                result.append(fix_segment(''.join(buf)))
                buf = []
            result.append(c)
        else:
            buf.append(c)
    if buf:
        result.append(fix_segment(''.join(buf)))
    return ''.join(result)


cases = [
    "浠嬬粛涓€涓?运动休闲卫衣",
    "浠婂ぉ涓嬮洦鍚?",
    "价格",
    "这件多少钱",
    "介绍一下 DRESS-001",
    "浠嬬粛涓€涓?简约黑色吊带裙",
    "有哪些商品",
    "你好吗?",
    "这件裙子多少钱",
    "今天下雨吗?",
]

for c in cases:
    fixed = fix_gbk_garbled(c)
    status = "FIXED" if fixed != c else "ok"
    print(f"[{status}] {c!r} -> {fixed!r}")
