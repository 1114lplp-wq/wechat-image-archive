"""Conservative, offline OCR hints. These hints are never verified facts."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DATE = r'(?:19|20)\d{2}[年./一-]\d{1,2}[月./一-]\d{1,2}日?'


def clean(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def safe_part(text, limit=28):
    text = INVALID.sub('', str(text or ''))
    text = re.sub(r'[，,。;；：:《》“”‘’…·「」『』]+', '', text)
    return re.sub(r'\s+', '', text).strip(' ._-')[:limit].rstrip(' ._-')


def get_lines(ocr):
    rows = []
    for line in ocr.get('lines', []):
        words = line.get('words') or []
        if not words:
            continue
        x, y = min(w['x'] for w in words), min(w['y'] for w in words)
        bottom = max(w['y'] + w['height'] for w in words)
        rows.append(dict(text=clean(line['text']), x=x, y=y,
                         height=bottom-y, cy=(y+bottom)/2))
    return sorted(rows, key=lambda r: (r['y'], r['x']))


def value_for(lines, labels, pattern):
    # Only a labelled line or text immediately to its right can supply a value.
    matches = []
    for line in lines:
        label = re.search(labels, line['text'])
        if not label:
            continue
        own = re.search(pattern, line['text'][label.end():])
        if own:
            matches.append((0, own.group(0)))
        for other in lines:
            if other is line or other['x'] <= line['x']:
                continue
            distance = abs(other['cy'] - line['cy'])
            if distance <= max(8, line['height'] * 0.65):
                match = re.search(pattern, other['text'])
                if match:
                    matches.append((distance + 1, match.group(0)))
    return min(matches)[1] if matches else None


def metadata(ocr):
    rows = get_lines(ocr)
    text = '\n'.join(r['text'] for r in rows)
    width, height = max(ocr.get('width', 1), 1), max(ocr.get('height', 1), 1)
    order = bool(re.search(r'订单编号|订单号|订单详情|订单信息|实付|交易成功|付款时间', text))
    date, date_label = None, None
    for label in ('创建时间', '下单时间', '付款时间', '支付时间', '交易时间', '签订日期', '签署日期'):
        raw = value_for(rows, label, DATE)
        if raw:
            try:
                date = dt.date(*map(int, re.findall(r'\d+', raw)[:3])).isoformat()
                date_label = label
                break
            except (ValueError, TypeError):
                pass
    # Never substitute a coupon expiry / delivery / unrelated date.
    order_id = value_for(rows, r'订单编号|订单号(?!保障)', r'\d{12,25}') if order else None
    platforms = ('天猫', '淘宝', '京东', '抖音商城', '拼多多', '1688')
    platform = next((p for p in platforms if p in text), None)
    excluded = (
        r'订单|收货|地址|电话|支付|交易|下架|推荐|售后|无理由|闲鱼|保障|优惠|'
        r'联系|配送|收件|合计|实付|采购车|购物车|再买|详情|退款|退货|发货|'
        r'物流|客服|评价|确认|删除|更多|颜色|尺寸|规格|旗舰|专卖|直营|自营|商铺|店铺'
    )
    titles = []
    for row in rows:
        value = row['text']
        if re.search(excluded, value) or re.search(r'\d{11}', value):
            continue
        if len(re.findall(r'[\u4e00-\u9fffA-Za-z]', value)) < 5:
            continue
        if not (0.08 * height < row['y'] < 0.40 * height):
            continue
        title = safe_part(re.sub(r'[¥￥].*$', '', value), 24)
        if title:
            titles.append(((0 if row['x'] > 0.18 * width else 1, row['y']), title))
    contracts = [safe_part(r['text'], 26) for r in rows
                 if r['y'] < height * .4 and re.search(r'合同|协议', r['text'])
                 and len(r['text']) <= 45]
    title = min(titles)[1] if titles else None
    if not order and contracts:
        title = contracts[0]
    return dict(kind=((platform or '') + '订单') if order else ('合同' if contracts else '图片'),
                platform=platform, date=date, date_label=date_label, title=title,
                order_id=order_id, amount=None, amount_verified=False,
                needs_review=True)


def make_filename(fields, extension, digest):
    # Even labelled OCR amounts can be wrong. No amount is used in automatic names.
    parts = ['待核对', fields.get('date'), fields.get('kind') or '图片',
             fields.get('title') or '内容待确认',
             '尾号' + fields['order_id'][-6:] if fields.get('order_id') else digest[:8]]
    return '_'.join(safe_part(p, 32) for p in parts if p) + extension
