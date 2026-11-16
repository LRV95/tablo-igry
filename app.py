# Табло игры «Рабочий день за 60 минут»: принимает подписанные строки движка со стенда GigaCowork
# (обычным POST или через MCP) и показывает рейтинг столов и итоги на отдельной странице.
import json, os, sqlite3, threading, time
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import game as g

DB = os.environ.get('TABLO_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tablo.db'))
PUSH_TOKEN = os.environ.get('PUSH_TOKEN', '')      # если задан — нужен для приёма результатов
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')    # нужен для сброса игры и переключения на итоги
LOCK = threading.Lock()
app = FastAPI(title='Табло · Рабочий день за 60 минут', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')), name='static')

def db():
    c = sqlite3.connect(DB)
    c.execute('create table if not exists tables(stol integer primary key, name text, t0 integer, tasks text, updated real)')
    c.execute('create table if not exists meta(key text primary key, value text)')
    return c

def meta_get(c, k, default=None):
    r = c.execute('select value from meta where key=?', (k,)).fetchone()
    return json.loads(r[0]) if r else default

def meta_set(c, k, v): c.execute('insert or replace into meta values(?,?)', (k, json.dumps(v, ensure_ascii=False)))

def load(c):
    return [dict(stol=s, name=n, t0=t0, tasks=json.loads(ts)) for s, n, t0, ts, _ in c.execute('select * from tables order by stol')]

def snapshot(tables): return {str(r['stol']): [r['rank'], r['points']] for r in g.rank(tables)}

def apply_text(text, final=None, admin=False):
    """Разбирает строки «ЗАПИСЬ» движка и вливает их в счёт. Две сдачи одного стола с разных ноутбуков не затирают друг друга."""
    tables, game, bad = g.parse(text)
    if not tables and not game and not admin:
        return dict(ok=False, error='не найдено ни одной строки движка с верной подписью', rejected=bad)
    with LOCK:
        c = db()
        cur = load(c)
        changed = False
        byid = {t['stol']: t for t in cur}
        for t in tables:
            old = byid.get(t['stol'])
            if old:
                tasks = dict(old['tasks'])
                for k, v in t['tasks'].items():
                    tasks[k] = min(v, tasks.get(k, v))
                name = t['name'] if not t['name'].startswith('Стол ') else old['name']
                new = dict(stol=t['stol'], name=name, t0=min(old['t0'], t['t0']), tasks=tasks)
                if new != old: changed = True
            else:
                new = t; changed = True
            byid[t['stol']] = new
        if changed:
            meta_set(c, 'prev', snapshot(cur))
            for t in byid.values():
                c.execute('insert or replace into tables values(?,?,?,?,?)', (t['stol'], t['name'], t['t0'], json.dumps(t['tasks']), time.time()))
        if game:
            old = meta_get(c, 'game')
            if old and game['start'] > old['start'] + 3600:
                # новая игра: столы прошлой игры убираем, режим — табло
                c.execute('delete from tables where t0 < ?', (game['start'] - 3600,))
                byid = {k: v for k, v in byid.items() if v['t0'] >= game['start'] - 3600}
                meta_set(c, 'prev', {}); meta_set(c, 'mode', 'tablo')
            meta_set(c, 'game', game)
        if final is not None:
            meta_set(c, 'mode', 'final' if final else 'tablo')
        c.commit()
        rows = g.rank(list(byid.values()))
        c.close()
    return dict(ok=True, tables=len(tables), game=bool(game), rejected=bad,
                rating=[dict(place=r['rank'], stol=r['stol'], team=r['name'], points=r['points'], hours=round(r['hours'], 1)) for r in rows])

def state():
    with LOCK:
        c = db(); tables = load(c); gm = meta_get(c, 'game'); prev = {int(k): v for k, v in meta_get(c, 'prev', {}).items()}; mode = meta_get(c, 'mode', 'tablo'); c.close()
    return tables, gm, prev, mode

def check(req, token):
    if token and req.headers.get('authorization', '') != 'Bearer ' + token:
        raise HTTPException(401, 'нужен токен')

PAGE = '''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Табло · Рабочий день за 60 минут</title><link rel="stylesheet" href="/static/igra.css">
<style>html{font-size:clamp(13px,.95vw + 4.6px,26px)}#app{min-height:100vh}.empty{padding:3rem 1rem;text-align:center;color:var(--tx2);border-radius:1.4rem;background:var(--n1)}
.row{transition:transform .5s var(--ease)}.lb .row{animation:none}</style></head>
<body><div id="app">%s</div><script>
const view=%s;
async function tick(){try{const r=await fetch('/fragment?view='+view,{cache:'no-store'});if(r.ok){const h=await r.text();const a=document.getElementById('app');if(a.innerHTML!==h)a.innerHTML=h;}}catch(e){}}
setInterval(tick,4000);
</script></body></html>'''

def fragment(view):
    tables, gm, prev, mode = state()
    v = mode if view == 'auto' else view
    return (g.final if v == 'final' else g.tablo)(tables, gm, prev)

@app.get('/', response_class=HTMLResponse)
def index(): return PAGE % (fragment('auto'), '"auto"')

@app.get('/final', response_class=HTMLResponse)
def final_page(): return PAGE % (fragment('final'), '"final"')

@app.get('/fragment', response_class=HTMLResponse)
def frag(view: str = 'auto'): return fragment(view if view in ('auto', 'tablo', 'final') else 'auto')

@app.get('/api/state')
def api_state():
    tables, gm, prev, mode = state()
    return dict(mode=mode, game=gm, rating=[dict(place=r['rank'], stol=r['stol'], team=r['name'], points=r['points'], hours=round(r['hours'], 1), answers=len(r['tasks'])) for r in g.rank(tables)])

@app.post('/api/push')
async def push(req: Request):
    check(req, PUSH_TOKEN)
    raw = (await req.body()).decode('utf-8', 'replace')
    final = None
    try:
        j = json.loads(raw); text = j.get('zapis') or j.get('text') or ''; final = j.get('final')
    except Exception:
        text = raw
    res = apply_text(text, final=bool(final) if final is not None else None)
    return JSONResponse(res, status_code=200 if res['ok'] else 400)

@app.post('/api/reset')
def reset(req: Request):
    check(req, ADMIN_TOKEN or 'не-задан')
    with LOCK:
        c = db(); c.execute('delete from tables'); c.execute('delete from meta'); c.commit(); c.close()
    return dict(ok=True)

@app.post('/api/mode')
async def mode(req: Request):
    check(req, ADMIN_TOKEN or 'не-задан')
    j = await req.json()
    return apply_text('', final=bool(j.get('final')), admin=True)

# ---------- MCP (Streamable HTTP, ответы JSON) ----------
TOOLS = [
    dict(name='zapisat_rezultat', description='Передать счёт стола на табло игры. Аргумент zapis — строка после «ЗАПИСЬ: » из вывода движка igra.py, дословно. '
         'Вызывай после каждой /старт, /сдать и /запуск. Для /финал передай final=true.',
         inputSchema=dict(type='object', properties=dict(zapis=dict(type='string', description='Строка движка: ST03|…|подпись или GAME|…'),
                                                          final=dict(type='boolean', description='true — переключить экран в зале на итоги')), required=['zapis'])),
    dict(name='pokazat_tablo', description='Текущий рейтинг столов на табло: место, команда, баллы, часы.', inputSchema=dict(type='object', properties={})),
]

def rpc_result(i, result): return dict(jsonrpc='2.0', id=i, result=result)

def handle_rpc(m):
    method, i, p = m.get('method'), m.get('id'), m.get('params') or {}
    if method == 'initialize':
        return rpc_result(i, dict(protocolVersion=p.get('protocolVersion', '2025-03-26'), capabilities=dict(tools=dict(listChanged=False)),
                                  serverInfo=dict(name='tablo-rabochiy-den', version='1.0'), instructions='Табло игры «Рабочий день за 60 минут».'))
    if method == 'ping':
        return rpc_result(i, {})
    if method == 'tools/list':
        return rpc_result(i, dict(tools=TOOLS))
    if method == 'tools/call':
        name, a = p.get('name'), p.get('arguments') or {}
        if name == 'zapisat_rezultat':
            res = apply_text(a.get('zapis', ''), final=a.get('final') if 'final' in a else None)
            if not res['ok']:
                return rpc_result(i, dict(isError=True, content=[dict(type='text', text='Не принято: ' + res['error'])]))
            top = '; '.join('%d. %s — %d' % (r['place'], r['team'], r['points']) for r in res['rating'][:5])
            return rpc_result(i, dict(content=[dict(type='text', text='Табло обновлено. ' + top)]))
        if name == 'pokazat_tablo':
            return rpc_result(i, dict(content=[dict(type='text', text=json.dumps(api_state(), ensure_ascii=False))]))
        return dict(jsonrpc='2.0', id=i, error=dict(code=-32602, message='нет такого инструмента'))
    if i is None:
        return None  # уведомление
    return dict(jsonrpc='2.0', id=i, error=dict(code=-32601, message='метод не поддерживается'))

@app.post('/mcp')
async def mcp(req: Request):
    check(req, PUSH_TOKEN)
    body = await req.json()
    out = [r for r in map(handle_rpc, body if isinstance(body, list) else [body]) if r is not None]
    if not out:
        return Response(status_code=202)
    return JSONResponse(out if isinstance(body, list) else out[0])

@app.get('/mcp')
def mcp_get(): return Response(status_code=405)

@app.get('/healthz')
def health(): return dict(ok=True)
