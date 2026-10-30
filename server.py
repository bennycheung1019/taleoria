#!/usr/bin/env python3
"""Run with python3 server.py. No third party packages required."""
import argparse
import errno
import webbrowser
import json
import secrets
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from kobold_rpg.illustrations import with_illustrations
from kobold_rpg.engine import Engine, RuleError, normalize_action, check_action
from kobold_rpg.model import draft, audit_narration, react, enrich_characters
from kobold_rpg.campaign import blank_campaign
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.story_world import generate_world
from kobold_rpg.play import interpret
from kobold_rpg.portable import export_file, MAX_BYTES
from kobold_rpg.storytypes import STORY_TYPES, DIFFICULTIES
from kobold_rpg.progress import ProgressStore, active
from kobold_rpg.jobs import JobStore
from kobold_rpg.names import aliases, display
from kobold_rpg.turn_updates import Runner, status as update_status, latest as pending_update
from kobold_rpg.physical import scene_text
from kobold_rpg.understanding import semantic_understanding,perceived_text
from kobold_rpg.settings import load_settings, validate_settings
from kobold_rpg.planning import semantic_action
from kobold_rpg.gm import reply as rpg_os_reply
from kobold_rpg.gm_context import recent_context,recalled_context

ROOT = Path(__file__).resolve().parent


def make_handler(engine, model_url, token, library=None, enricher=None, planner=semantic_action, gm=rpg_os_reply, save_connection=None):
    initial_engine = engine
    model_lock = threading.Lock()
    operation_lock = library.lock if library is not None else threading.RLock()
    progress=ProgressStore()
    jobs=JobStore()
    background=Runner(operation_lock,model_url,enricher or enrich_characters)

    def retire_old_indexing(engine):
        if gm is not None:
            with engine.connect() as db:
                db.execute("UPDATE turn_updates SET status='done',error=NULL WHERE status!='done'")

    retire_old_indexing(engine)

    def history(engine, rows=None):
        result = []
        for row in (engine.history() if rows is None else rows):
            if row['status']=='enrichment':continue
            item = {k: row[k] for k in ('revision', 'status', 'narration', 'at')}
            declaration = row.get('action', {}).get('text', '')
            item['declaration'] = '' if declaration.startswith('【') else declaration
            result.append(item)
        return display(result,aliases(engine.state()))

    def frame(engine):
        state=engine.state();pc=state['pc'];place=state['locations'][pc['location']]
        identity=state.get('canon',{}).get('actors',{}).get(pc['id'],{})
        result={'campaign_id':state['campaign_id'],'revision':state['revision'],
                'session_id':library.session_id if library is not None else '',
                'contract':state['contract'],'pc':{**{key:pc[key] for key in ('id','name','alive','location')},
                    'role':pc.get('role',identity.get('role','')),'species':pc.get('species',identity.get('species',''))},
                'scene':{'name':place['name'],'description':scene_text(state)}}
        return display(result,aliases(state))

    def turn(engine,revision):
        with engine.connect() as db:
            row=db.execute('SELECT body FROM journal WHERE revision=?',(revision,)).fetchone()
        data=json.loads(row['body'])
        return history(engine,[{'revision':revision,**data}])[0]

    def player_session(engine):
        retire_old_indexing(engine)
        views=update_status(engine)
        if views['status']!='ready':
            return {'state':None,'panel_snapshot':panel_snapshot(engine),'frame':frame(engine),'history':history(engine),'views':views}
        if library is not None:
            state,rows=library.session_snapshot();result={'state':state,'history':history(engine,rows),'views':views}
        else:result={'state':engine.public_state(),'history':history(engine),'views':views}
        if update_status(engine)['status']!='ready':
            return {'state':None,'panel_snapshot':panel_snapshot(engine),'frame':frame(engine),'history':history(engine),'views':update_status(engine)}
        return result

    def panel_snapshot(engine):
        # Physical outcomes are already committed. Background work can only add
        # social memories/public notes; existing confirmed public data stays valid.
        if library is not None:return library.session_snapshot()[0]
        return engine.public_state()

    def execute_post(path, body):
        nonlocal model_url
        with operation_lock:
            job=None;context_token=None;success=False
            try:
                engine = library.engine if library is not None else initial_engine
                if library is not None:
                    library.check_session(body.get('session_id'))
                with engine.connect() as db:
                    duplicate=path=='/api/play' and db.execute('SELECT revision,body FROM journal WHERE request_id=?',(body.get('request_id'),)).fetchone()
                if gm is None and pending_update(engine) and path!='/api/updates/retry' and not duplicate:
                    raise RuleError('上一段故事已發生，人物紀錄整理完成後就能繼續。')
                if path in {'/api/play','/api/world/draft'}:
                    request=body.get('request_id',secrets.token_urlsafe(18) if path=='/api/world/draft' else None)
                    if not isinstance(request,str) or not 1<=len(request)<=120:
                        raise RuleError('需要有效的行動識別。')
                    job=progress.start(body.get('session_id',''),request,2 if path=='/api/world/draft' else 1 if gm is not None else 3 if planner is not None else 2)
                    context_token=active.set(job)
                if path == '/api/connection/settings':
                    from kobold_rpg.illustrations import endpoint_url
                    value=endpoint_url(body.get('model_url'))
                    if save_connection:save_connection(value)
                    model_url=value
                    Handler.illustrations.model_url=value
                    result={'model_url':value}
                elif path == '/api/world/draft' and library is not None:
                    candidate=generate_world(body.get('preferences'), model_url, library.root/'drafts')
                    result=display(library.preview(candidate),aliases(candidate['seed']))
                elif path == '/api/world/create' and library is not None:
                    result = library.create(body['preview_id'])
                elif path == '/api/save' and library is not None:
                    result = library.save(body['name'])
                elif path == '/api/load' and library is not None:
                    result = library.load(body['kind'], body['id'])
                elif path == '/api/import-file' and library is not None:
                    result = library.import_file(body['save'])
                elif path == '/api/updates/retry':
                    background.retry(engine);result={'views':update_status(engine)}
                elif path == '/api/play':
                    if gm is not None:
                        retire_old_indexing(engine)
                        if duplicate:
                            action=json.loads(duplicate['body'])['action']
                            if action['text']!=body.get('text'):raise RuleError('同一行動識別不能改成另一句宣告。')
                            prior=json.loads(duplicate['body'])
                            result={'status':prior['status'],'narration':prior['narration'],
                                    'revision':duplicate['revision']}
                        else:
                            state=engine.state()
                            if state.get('setup_required'):raise RuleError('先建立你的世界，再開始冒險。')
                            recent,provenance=recent_context(engine,state)
                            recalled=recalled_context(engine,state,body.get('text') or '',[row['revision'] for row in recent])
                            if recalled:provenance['recalled_exchanges']=recalled
                            response=gm(state,body.get('text'),model_url,recent=recent,state_provenance=provenance)
                            result=engine.record_gm_reply(body.get('text'),response,body['request_id'],state['revision'])
                        result={**display(result,aliases(engine.state())),'turn':turn(engine,result['revision']),
                                'frame':frame(engine),'panel_snapshot':panel_snapshot(engine),'views':update_status(engine)}
                        success=True
                        return 200,result
                    if duplicate:
                        action=json.loads(duplicate['body'])['action']
                        if action['text']!=body.get('text'):raise RuleError('同一行動識別不能改成另一句宣告。')
                    else:
                        state = engine.state()
                        if body.get('revision') != state['revision']:
                            raise RuleError('世界已更新，請重新載入再裁定')
                        if planner is not None:
                            action = planner(state, body.get('text'), model_url)
                        else:
                            # Explicit compatibility seam for legacy clients/tests.
                            action = interpret(state, body.get('text'), body.get('intent'),
                                resolver=lambda text:semantic_understanding(text,model_url))
                    result = engine.submit(action, body['request_id'], body['revision'])
                    if result['status'] == 'review':
                        state = engine.state()
                        with engine.connect() as db:
                            records=[(row['revision'],json.loads(row['body']),json.loads(row['before_state']))
                                     for row in db.execute('SELECT revision,body,before_state FROM journal ORDER BY revision DESC LIMIT 32')]
                            recent=[{'revision':revision,'target':row['action'].get('target',''),'kind':row['action']['kind'],'has_events':bool(row['events']),
                                     'witnesses':[key for key,npc in before['npcs'].items() if npc['known'] and npc['location']==before['pc']['location']],
                                     'declaration':perceived_text(row['action']),'narration':row['narration']}
                                    for revision,row,before in records if row['status']=='approved'][:4]
                        proposal = react(state, action, model_url,recent=list(reversed(recent)))
                        audit = audit_narration(state, action, proposal, model_url,structured=action['kind']=='speak')
                        checked=engine.propose(action, proposal, state['revision'], 'koboldcpp', audit)
                        result=engine.approve(checked['id'],body['request_id'],defer_people=True)
                    result={**display(result,aliases(engine.state())),'turn':turn(engine,result['revision']),
                            'frame':frame(engine),'panel_snapshot':panel_snapshot(engine),'views':update_status(engine)}
                elif path == "/api/act":
                    result = engine.submit(body["action"], body["request_id"], body["revision"])
                elif path == "/api/draft":
                    state = engine.state()
                    action = normalize_action(body["action"])
                    if body["revision"] != state["revision"]:
                        raise RuleError("世界已更新")
                    if check_action(state, action)[0] != "review":
                        raise RuleError("這項行動已有前提裁定，不呼叫模型")
                    if not model_lock.acquire(blocking=False):
                        raise RuleError("模型正處理另一個裁定，請稍後再試")
                    try:
                        proposal = draft(state, action, model_url)
                        audit = audit_narration(state, action, proposal, model_url)
                        result = engine.propose(action, proposal, body["revision"], "koboldcpp", audit)
                    finally:
                        model_lock.release()
                elif path == "/api/propose":
                    state = engine.state()
                    action = normalize_action(body['action'])
                    if body['revision'] != state['revision']:
                        raise RuleError('世界已更新')
                    if not model_lock.acquire(blocking=False):
                        raise RuleError('模型正處理另一個裁定，請稍後再試')
                    try:
                        audit = audit_narration(state, action, body['proposal'], model_url)
                        result = engine.propose(action, body['proposal'], body['revision'], 'human', audit)
                    finally:
                        model_lock.release()
                elif path == '/api/establish' and body.get('confirmed') is True:
                    result = engine.establish(body['definition'], body['source'], body['revision'], body['request_id'])
                elif path == "/api/approve":
                    result = engine.approve(body["proposal_id"], body["request_id"])
                elif path == "/api/rewind":
                    result = engine.rewind(body["target_revision"], body["revision"], body["request_id"])
                elif path == "/api/grant-spell" and body.get("confirmed") is True:
                    result = engine.grant_spell(body["ability_id"], body["definition"], body["revision"], body["request_id"])
                elif path == "/api/maintain" and body.get("confirmed") is True:
                    result = engine.maintain(body["changes"], body["source"], body["revision"], body["request_id"])
                else:
                    return 404, {"error": "找不到操作"}
                success=True
                background.kick(library.engine if library is not None else engine)
                return 200, result
            except (KeyError,TypeError):
                return 400, {'error':'回應資料不完整，這次操作沒有完成。請重新整理確認故事進度後再繼續。'}
            except (RuleError, ValueError) as exc:
                return 400, {"error": str(exc)}
            except Exception:
                return 500, {"error": "操作未完成；請重新載入狀態，勿假設已成功"}
            finally:
                if job:job.finish(success)
                if context_token is not None:active.reset(context_token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, code, body, content_type="application/json; charset=utf-8"):
            data = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # A departed browser cannot cancel or corrupt a server task.
                pass

        def do_GET(self):
            engine = library.engine if library is not None else initial_engine
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self.send(200, (ROOT / "ui.html").read_text().replace("__SESSION_TOKEN__", token), "text/html; charset=utf-8")
            elif path in {'/app.js', '/connection.js', '/styles.css'}:
                self.send(200, (ROOT / path[1:]).read_text(),
                          'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            elif path in {'/taleoria-mark.svg','/favicon.svg'}:
                self.send(200,(ROOT/path[1:]).read_text(),'image/svg+xml; charset=utf-8')
            elif path == '/api/session':
                self.send(200,player_session(engine))
                if self.headers.get('X-RPG-Token')==token:background.kick(engine)
            elif path == '/api/panels' and self.headers.get('X-RPG-Token')==token:
                try:
                    if library is not None:library.check_session(self.headers.get('X-RPG-Session'))
                    self.send(200,player_session(engine));background.kick(engine)
                except RuleError as exc:self.send(400,{'error':str(exc)})
            elif path == "/api/state":
                if pending_update(engine):self.send(202,{'frame':frame(engine),'views':update_status(engine)})
                else:self.send(200, library.public_state() if library is not None else engine.public_state())
            elif path == "/api/history":
                # Player timeline omits private facts and review rationale.
                self.send(200, history(engine))
            elif path == '/api/library' and self.headers.get('X-RPG-Token') == token and library is not None:
                self.send(200, library.list())
            elif path == '/api/creation-options':
                self.send(200, {'story_types':STORY_TYPES,'difficulties':DIFFICULTIES})
            elif path == '/api/jobs' and self.headers.get('X-RPG-Token') == token:
                query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                session=self.headers.get('X-RPG-Session','')
                request=query.get('request_id',[''])[0]
                result=jobs.snapshot(session,request)
                if result is None:
                    self.send(404, {'error':'找不到這次生成，服務可能已重新啟動。請確認故事進度後再繼續。'})
                else:
                    self.send(200, {**result, 'progress': progress.snapshot(session,request)})
            elif path == '/api/progress' and self.headers.get('X-RPG-Token') == token:
                query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                session=self.headers.get('X-RPG-Session','')
                self.send(200,progress.snapshot(session,query.get('request_id',[''])[0]))
            elif path == '/api/save-file' and self.headers.get('X-RPG-Token') == token:
                try:
                    if library is not None:
                        with library.selection_lock:
                            library.check_session(self.headers.get('X-RPG-Session'))
                            engine=library.engine
                    if pending_update(engine):raise RuleError('人物紀錄仍在整理，完成後才能下載完整存檔。')
                    self.send(200, export_file(engine))
                except RuleError as exc:
                    self.send(400,{'error':str(exc)})
            elif path == "/api/export" and self.headers.get("X-RPG-Token") == token:
                self.send(200, {"format": "kobold-rpg-0.3", "state": engine.state(), "history": engine.history(), "verified": engine.verify()})
            elif path == "/api/gm/npcs" and self.headers.get("X-RPG-Token") == token:
                state = engine.state()
                self.send(200, {"revision": state["revision"], "npcs": state["npcs"]})
            elif path == '/api/gm/canon' and self.headers.get('X-RPG-Token') == token:
                state = engine.state()
                self.send(200, {'revision': state['revision'], 'canon': state.get('canon')})
            elif path == '/api/connection':
                try:
                    with urllib.request.urlopen(model_url + '/api/v1/model', timeout=3) as response:
                        model = json.load(response)['result']
                    connected = True
                except Exception:
                    connected, model = False, None
                self.send(200, {'engine': 'Taleoria 0.10 · RPG OS story director', 'model_url': model_url,
                                'connected': connected, 'model': model,
                                'canon_checks': 'canon' in engine.state()})
            elif path == "/health":
                self.send(200, {"ok": True, "revision": engine.state()["revision"], "journal_verified": engine.verify()})
            else:
                self.send(404, {"error": "找不到頁面"})

        def do_POST(self):
            if self.headers.get("X-RPG-Token") != token:
                self.send(403, {"error": "請從本機介面操作"})
                return
            try:
                path = urllib.parse.urlparse(self.path).path
                size = int(self.headers.get("Content-Length", "0"))
                limit=MAX_BYTES*2 if path=='/api/import-file' else 65536
                if not 0 < size <= limit:
                    raise RuleError("請求過大或沒有內容")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise RuleError("需要 JSON 物件")
                if self.headers.get('Prefer') == 'respond-async' and path in {'/api/play', '/api/world/draft'}:
                    if library is not None:library.check_session(body.get('session_id'))
                    jobs.start(path, body, lambda: execute_post(path, body))
                    self.send(202, {'request_id': body['request_id']})
                else:
                    code, result = execute_post(path, body)
                    self.send(code, result)
            except (RuleError, ValueError) as exc:
                self.send(400, {'error': str(exc)})

    Handler.jobs=jobs
    Handler.background=background
    return with_illustrations(Handler, engine, model_url, token, library, operation_lock)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='Taleoria JSON 設定檔；預設 taleoria.local.json')
    parser.add_argument("--port", type=int)
    parser.add_argument("--db")
    parser.add_argument("--model-url")
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    try:
        values = load_settings(ROOT, args.config)
        for key in ('port', 'db', 'model_url'):
            if getattr(args, key) is not None: values[key] = getattr(args, key)
        values = validate_settings(ROOT, values)
    except (ValueError, OSError, RuleError) as exc:
        parser.error(str(exc))
    args.port, args.db, args.model_url = values['port'], values['db'], values['model_url']
    engine = Engine(args.db, seed=blank_campaign())
    engine.verify()
    library_name = 'library' if engine.path.parent.resolve() == (ROOT / 'data').resolve() else engine.path.stem + '-library'
    library = CampaignLibrary(engine.path.parent / library_name, engine)
    try:
        from kobold_rpg.companion import load_config,with_companion
        config_path=ROOT/'data/companion.json'
        companion=load_config(config_path)
        token=secrets.token_urlsafe(32)
        def save_connection(value):
            path=Path(args.config) if args.config else ROOT/'taleoria.local.json'
            if not path.is_absolute():path=ROOT/path
            data=json.loads(path.read_text()) if path.exists() else {}
            data['model_url']=value
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2));temporary.replace(path)
        handler=make_handler(engine,args.model_url,token,library,save_connection=save_connection)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), with_companion(handler,token,companion,config_path))
    except OSError as exc:
        hint = (f'請先關閉佔用 {args.port} 的舊 Taleoria，或修改 port。' if exc.errno == errno.EADDRINUSE
                else '目前環境未允許啟動本機服務；請在自己的終端執行啟動檔。')
        parser.exit(1, f'無法啟動 Taleoria：{exc}\n{hint}\n')
    print(f'Project: {ROOT}\nDatabase: {engine.path}\nKoboldCpp: {args.model_url}', flush=True)
    print(f"Taleoria｜千語之境 ready: http://127.0.0.1:{args.port}", flush=True)
    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}/')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.RequestHandlerClass.jobs.join()
        server.RequestHandlerClass.background.join()
        server.RequestHandlerClass.illustrations.join()


if __name__ == "__main__":
    main()
