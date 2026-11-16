# Данные и правила игры «Рабочий день за 60 минут» — те же, что в движке igra.py на стенде.
# Здесь: проверка подписи строк движка, счёт столов и разметка табло и итогов.
import hashlib, html, os, re, time

# Ключ подписи — тот же, что в движке igra.py на стенде. Хранится только в переменной окружения, не в коде.
SALT = os.environ.get('TABLO_SALT', '')
DUR = 40
# id, отдел, ситуация, часы вручную, вопросов
T = [('1', 'Продажи · юристы', 'Претензия и срочное предложение', 3.5, 3), ('2', 'Закупки · юристы', 'Двигатели и договор на арматуру', 5.0, 3),
     ('3', 'Финансы · продажи', 'Совет директоров в 10:00', 10.0, 3), ('4', 'Кадры', 'Конструктор и новый технолог', 4.0, 3),
     ('5', 'Производство · приёмная', 'Простои и планёрка', 4.0, 3), ('6', 'Клиентский сервис', 'Клиенты жалуются', 3.0, 3)]
G = [('7', 'Аврал · юристы', 'Второй договор на подпись', 2.0, 1), ('8', 'Аврал · закупки', 'Новые предложения по двигателям', 3.0, 1),
     ('9', 'Аврал · финансы', 'Продажи за октябрь и ноябрь', 4.0, 1)]
SIT = {t[0]: t for t in T + G}
CH = [(t[0] + 'abc'[k], t[0], 2 if t in G else 1, t[3] / t[4]) for t in T + G for k in range(t[4])]
ALL = {c[0]: c for c in CH}
TOTAL_P = sum(t[4] for t in T)
E = html.escape

def sig(*parts):
    return hashlib.sha256((SALT + '#' + '|'.join(str(p) for p in parts)).encode('utf-8')).hexdigest()[:8]

LINE = re.compile(r'(?:ST|СТ|S|С|C)(\d\d)\|([^|\n]*)\|(\d{9,11})\|([0-9abc,\-]*)\|([0-9a-f]{8})')
GAME = re.compile(r'GAME\|(\d{9,11})\|(\d{1,3})\|([0-9a-f]{8})')

def parse(text):
    """Строки столов и часов игры из текста; строки с неверной подписью отбрасываются."""
    tables, game, bad = [], None, 0
    if not SALT:
        return tables, game, bad
    for m in LINE.finditer(str(text)):
        stol, name, t0, ts, s = int(m.group(1)), m.group(2).strip(), int(m.group(3)), m.group(4), m.group(5)
        if s != sig(stol, t0, ts):
            bad += 1
            continue
        tasks = {}
        for part in filter(None, ts.split(',')):
            k, _, v = part.partition('-')
            if k in ALL and v.isdigit():
                tasks[k] = int(v)
        tables.append(dict(stol=stol, name=name or 'Стол %d' % stol, t0=t0, tasks=tasks))
    for m in GAME.finditer(str(text)):
        if m.group(3) == sig('game', m.group(1), m.group(2)):
            game = dict(start=int(m.group(1)), dur=int(m.group(2)))
        else:
            bad += 1
    return tables, game, bad

def fmt(h): return ('%.1f' % h).rstrip('0').rstrip('.').replace('.', ',')
def pl(n, a, b, c):
    n = abs(int(n)); return a if n % 10 == 1 and n % 100 != 11 else b if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else c

def rank(tables):
    rows = []
    for t in tables:
        pts = sum(ALL[k][2] for k in t['tasks']); hrs = sum(ALL[k][3] for k in t['tasks'])
        last = max([t['t0'] + v * 60 for v in t['tasks'].values()] or [t['t0']])
        rows.append(dict(t, points=pts, hours=hrs, last=last))
    rows.sort(key=lambda r: (-r['points'], -r['hours'], r['last'], r['stol']))
    for i, r in enumerate(rows): r['rank'] = i + 1
    return rows

BOT = '<span class="bot"><i></i></span>'
def segs(done): return ''.join('<s class="%s%s" style="--w:%s"></s>' % ('on ' if c[0] in done else '', 'sk' if int(c[1]) > 6 else '', round(c[3], 2)) for c in CH)
def nav(chips): return '<div class="nav"><span class="logo"></span>' + chips + '</div>'

def clock(game):
    if not game:
        return '<span class="btn" style="background:#fff;color:#8c949e">часы игры ещё не запущены</span>'
    left = game['start'] + game['dur'] * 60 - int(time.time())
    if left <= 0:
        return '<span class="btn low"><b>Время вышло</b></span>'
    return '<span class="btn%s"><b>%d мин</b> до конца игры</span>' % (' low' if left < 300 else '', (left + 59) // 60)

def row(r, i, prev):
    p = prev.get(r['stol'])
    mv = '<i></i>'
    if p:
        if p[0] > r['rank']: mv = '<i class="up">▲%d</i>' % (p[0] - r['rank'])
        elif p[0] < r['rank']: mv = '<i style="color:#d9423c">▼%d</i>' % (r['rank'] - p[0])
        elif r['points'] > p[1]: mv = '<i class="up">+%d</i>' % (r['points'] - p[1])
    return ('<li class="row r%d"><span class="rk">%d</span><span class="nm"><b>%s</b><i>стол %d</i></span><span class="segs">%s</span><span class="hr">%s ч</span><span class="pt"><b>%d</b>%s</span></li>' % (
        r['rank'], r['rank'], E(r['name']), r['stol'], segs(r['tasks']), fmt(r['hours']), r['points'], mv))

def head(rows, final):
    n_ans = sum(len(r['tasks']) for r in rows); hours = sum(r['hours'] for r in rows)
    h1 = ('Директор принял <em>%d</em> %s — <em>%s</em> ч ручной работы' % (n_ans, pl(n_ans, 'ответ', 'ответа', 'ответов'), fmt(hours))) if n_ans else 'Ждём первый доклад директору'
    return h1, hours

def tablo(tables, game, prev):
    rows = rank(tables); n = len(rows)
    h1, _ = head(rows, False)
    chips = '<span class="chip"><i>В игре</i>%d %s</span>%s' % (n, pl(n, 'стол', 'стола', 'столов'), clock(game))
    h = '<section class="hero">' + nav(chips) + '<div><p class="eye">Табло · Рабочий день за 60 минут</p><h1>%s</h1></div></section>' % h1
    if not rows:
        return h + '<p class="empty">Пока ни один стол не начал. Каждый стол запускает игру командой /старт на стенде.</p>'
    h += '<div class="cols"><span>№</span><span>Команда</span><span>%d вопросов директора и %d аврала</span><span>Часы</span><span>Баллы</span></div>' % (TOTAL_P, len(G))
    h += '<ol class="lb">' + ''.join(row(r, i, prev) for i, r in enumerate(rows)) + '</ol>'
    ev = sorted(((r['t0'] + v * 60, r['name'], k) for r in rows for k, v in r['tasks'].items()), reverse=True)[:8]
    h += '<div class="tick"><b>Последние ответы</b><div>' + (''.join('<span><b>%s</b> · %s <em>+%d</em></span>' % (E(nm), E(SIT[ALL[k][1]][2]), ALL[k][2]) for _, nm, k in ev)
                                                         or '<span>Пока пусто: первый доклад откроет ленту</span>') + '</div></div>'
    return h

def final(tables, game, prev):
    rows = rank(tables); n = len(rows)
    h1, hours = head(rows, True)
    h = '<section class="hero">' + nav('<span class="chip"><i>В игре</i>%d %s</span>' % (n, pl(n, 'стол', 'стола', 'столов'))) + '<div><p class="eye">Итоги игры · Рабочий день за 60 минут</p><h1>%s</h1></div></section>' % h1
    if not rows:
        return h + '<p class="empty">Итоги появятся, когда столы начнут играть.</p>'
    h += '<section class="pod">'
    for i, k in enumerate([1, 0, 2]):
        if k >= n:
            h += '<div></div>'; continue
        r = rows[k]
        h += ('<div class="pd p%d" style="--h:%s"><div class="hd"><span class="md">%d</span>%s</div><h3>%s</h3><p>стол %d</p>'
              '<div class="sc"><span><b>%d</b> %s</span><span><b>%s</b> ч ручной работы</span><span><b>%d</b> %s</span></div></div>') % (
            r['rank'], ['10.5rem', '13rem', '9.5rem'][i], r['rank'], BOT if r['rank'] == 1 else '', E(r['name']), r['stol'], r['points'], pl(r['points'], 'балл', 'балла', 'баллов'),
            fmt(r['hours']), len(r['tasks']), pl(len(r['tasks']), 'верный ответ', 'верных ответа', 'верных ответов'))
    h += '</section>'
    days = max(1, round(hours / 8)); mins = game['dur'] if game else DUR
    sk = lambda r: len([k for k in r['tasks'] if int(k[0]) > 6]); best = max(rows, key=sk)
    ev = sorted((r['t0'] + v * 60, r['name'], k, v) for r in rows for k, v in r['tasks'].items())
    h += '<section class="facts"><div class="fact"><i>Что это значит</i><b>%s ч ручной работы за %d минут</b><span>Одному сотруднику на это нужно %d %s.</span></div>' % (fmt(hours), mins, days, pl(days, 'рабочий день', 'рабочих дня', 'рабочих дней'))
    if ev:
        h += '<div class="fact"><i>Первый верный ответ</i><b>%s — на %d-й минуте</b><span>«%s»</span></div>' % (E(ev[0][1]), ev[0][3], E(SIT[ALL[ev[0][2]][1]][2]))
    if sk(best):
        h += '<div class="fact"><i>Аврал</i><b>%s — %d из %d в аврале</b><span>Подход сохранили как навык и запустили на новых документах.</span></div>' % (E(best['name']), sk(best), len(G))
    else:
        h += '<div class="fact"><i>Следующий шаг</i><b>Навык вместо повторной работы</b><span>Решение сохраняется как навык и запускается на новых данных за минуту.</span></div>'
    h += '</section>'
    if n > 3:
        h += '<ol class="lb">' + ''.join(row(r, i, prev) for i, r in enumerate(rows[3:])) + '</ol>'
    return h
