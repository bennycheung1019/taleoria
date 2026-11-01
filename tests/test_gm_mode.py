import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine
from kobold_rpg.gm import decode_reply, record_changes, reply, rules_packet
from kobold_rpg.portable import export_file, validate_file
from server import make_handler


class GMReplyTests(unittest.TestCase):
    def test_fresh_campaign_has_only_state_and_journal_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'fresh.sqlite3',seed=new_campaign())
            with engine.connect() as db:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables,{'state','journal'})
            self.assertEqual(engine.state()['revision'],0)

    def test_rules_are_original_rpg_os_gm_cycle_and_freeform(self):
        rules=rules_packet()
        self.assertIn('Understand',rules);self.assertIn('Establish',rules)
        self.assertIn('Resolve',rules);self.assertIn('Portray',rules)
        self.assertIn('Resolve uncertain outcomes by GM judgment',rules)
        self.assertIn('refusal is not a default personality',rules)

    def test_model_receives_original_declaration_in_one_call(self):
        text='唔同佢爭論, 收起刀, 行近佢'
        with patch('kobold_rpg.model._complete',return_value='{"narration":"安雅看見你收刀，抬頭回應。","changes":{}}') as model:
            result=reply(new_campaign(),text,'http://local')
        model.assert_called_once()
        messages=model.call_args.args[0]
        self.assertEqual(messages[-1],{'role':'user','content':text})
        self.assertTrue(model.call_args.kwargs['raw'])
        self.assertEqual(result['narration'],'安雅看見你收刀，抬頭回應。')

    def test_plain_reply_or_incomplete_metadata_does_not_block_story(self):
        for raw in ('安雅抬頭：「雨大，小心腳下。」',
                    '{"narration":"安雅看見你收刀。","changes":{"pc":',
                    '{"narration":"安雅看見你收刀。","changes":["wrong shape"]}'):
            with self.subTest(raw=raw):
                result=decode_reply(raw)
                self.assertTrue(result['narration']);self.assertEqual(result['changes'],{})

    def test_world_changes_are_gm_authored_not_checked_by_gameplay_vetoes(self):
        state=new_campaign()
        changes={'pc':{'location':'pier','equipment_notes':'獵刀已收好','alive':False},
                 'npcs':{'anya':{'encounter':{'stance':'較放鬆，但尚未承諾載客'}}},
                 'facts_add':['班把刀收好。']}
        after,status=record_changes(state,changes,1)
        self.assertEqual(status,'ready');self.assertEqual(after['pc']['location'],'pier')
        self.assertFalse(after['pc']['alive'])
        self.assertEqual(state['pc']['location'],'gate')
        self.assertEqual(after['facts'][-1]['text'],'班把刀收好。')

    def test_new_character_is_saved_without_manual_registration_gate(self):
        state=new_campaign()
        after,status=record_changes(state,{'npcs':{'traveller':{'name':'旅人（Traveller）','description':'穿著舊雨衣的成年旅人。',
                         'species':'人類','role':'旅人','location':'gate'}}},1)
        self.assertEqual(status,'ready');self.assertIn('traveller',after['npcs'])
        self.assertIn('traveller',after['canon']['actors'])

    def test_one_misplaced_metadata_field_does_not_discard_usable_character_changes(self):
        after,status=record_changes(new_campaign(),{'pc':{'equipment_notes':'刀已收起'},
            'npcs':{'anya':{'encounter':{'stance':'稍微放鬆'}},'location':'pier'}},1)
        self.assertEqual(status,'partial')
        self.assertEqual(after['pc']['equipment_notes'],'刀已收起')
        self.assertEqual(after['npcs']['anya']['encounter']['stance'],'稍微放鬆')

    def test_unusable_bookkeeping_keeps_story_and_portable_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'gm.sqlite3',seed=new_campaign());before=engine.state()
            text='唔同佢爭論, 收起刀, 行近佢'
            result=engine.record_gm_reply(text,{'narration':'你把刀收好，走近她。','changes':{'pc':{'location':'missing_place'}}},'turn',0)
            self.assertEqual(result['status'],'approved')
            after=engine.state();self.assertEqual(after['pc'],before['pc'])
            self.assertEqual(engine.history()[0]['bookkeeping'],'incomplete')
            self.assertEqual(engine.history()[0]['action']['text'],text)
            self.assertTrue(engine.verify());validate_file(export_file(engine))


class GMDefaultAPITests(unittest.TestCase):
    def test_retired_gameplay_routes_do_not_change_story(self):
        before=self.engine.state()
        for path in ('/api/act','/api/draft','/api/propose','/api/approve',
                     '/api/establish','/api/rewind','/api/grant-spell',
                     '/api/maintain','/api/updates/retry'):
            with self.subTest(path=path):
                conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
                try:
                    conn.request('POST',path,'{}',{'Content-Type':'application/json','X-RPG-Token':'test'})
                    response=conn.getresponse();response.read()
                    self.assertEqual(response.status,404)
                finally:conn.close()
        self.assertEqual(self.engine.state(),before)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        seed=new_campaign();seed['pc']['alive']=False
        self.engine=Engine(Path(self.tmp.name)/'game.sqlite3',seed=seed)
        self.handler=make_handler(self.engine,'http://model','test')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.handler.jobs.join();self.handler.illustrations.join()

    def send(self,text,request='gm',revision=0):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            conn.request('POST','/api/play',json.dumps({'text':text,'request_id':request,'revision':revision}),
                         {'Content-Type':'application/json','X-RPG-Token':'test'})
            response=conn.getresponse();return response.status,json.loads(response.read())
        finally:conn.close()

    def test_old_metadata_tail_is_hidden_in_session_history_and_duplicate_response_without_rewriting_journal(self):
        from test_narration_boundary import LEAK,PROSE
        state=self.engine.state()
        with self.engine.connect() as db:
            self.engine._append(db,state,copy.deepcopy(state),'legacy',{'status':'approved',
                'action':{'kind':'freeform','text':'問路'},'narration':LEAK,'events':[],'bookkeeping':'ready'})
        with self.engine.connect() as db:before=tuple(db.execute('SELECT body,hash FROM journal').fetchone())
        for path in ('/api/session','/api/history'):
            conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
            try:
                conn.request('GET',path,headers={'X-RPG-Token':'test'})
                response=conn.getresponse();data=json.loads(response.read())
            finally:conn.close()
            self.assertEqual(response.status,200)
            rows=data['history'] if path=='/api/session' else data
            self.assertEqual(rows[0]['narration'],PROSE)
        with patch('kobold_rpg.model._complete',side_effect=AssertionError('never replay this turn')):
            code,result=self.send('問路',request='legacy')
        self.assertEqual(code,200);self.assertEqual(result['narration'],PROSE)
        self.assertEqual(result['turn']['narration'],PROSE)
        with self.engine.connect() as db:after=tuple(db.execute('SELECT body,hash FROM journal').fetchone())
        self.assertEqual(after,before);self.assertTrue(self.engine.verify())

    def test_default_route_has_no_parser_rule_veto_or_second_model_audit(self):
        text='OOC: why can I not use fire magic?'
        raw=json.dumps({'narration':'OOC：目前尚未學會魔法，施法仍要依世界事實裁定。','changes':{}},ensure_ascii=False)
        with patch('kobold_rpg.model._complete',return_value=raw) as model:
            code,result=self.send(text,revision=999)
            self.assertEqual(code,200,result)
            code,retry=self.send(text,revision=999)
            self.assertEqual(code,200,retry)
        model.assert_called_once()
        self.assertEqual(result['narration'],retry['narration'])
        self.assertEqual(self.engine.state()['revision'],1)
        self.assertEqual(result['views']['status'],'ready')

    def test_source_correction_saves_only_final_story_and_is_not_replayed(self):
        bad={'player_power_uses':[{'ability_id':'fire','manifested':True}],
             'narration':'空地燃起火焰。','changes':{'facts_add':['空地被火焰燒過。']}}
        fixed={'player_power_uses':[{'ability_id':'','manifested':False}],
               'narration':'你嘗試施法，但沒有產生火焰。','changes':{}}
        with patch('kobold_rpg.model._complete',side_effect=[bad,fixed]) as model:
            code,result=self.send('我對空地嘗試施展火焰魔法。')
            code,retry=self.send('我對空地嘗試施展火焰魔法。')
        self.assertEqual(code,200,result)
        self.assertEqual(model.call_count,2)
        self.assertEqual(result['narration'],fixed['narration'])
        self.assertEqual(retry['narration'],fixed['narration'])
        self.assertNotIn('空地被火焰燒過。',[fact['text'] for fact in self.engine.state()['facts']])
        history=self.engine.history()
        self.assertEqual(len(history),1)
        self.assertTrue(history[0]['ability_source_correction'])
        self.assertTrue(self.engine.verify())
        validate_file(export_file(self.engine))


if __name__=='__main__':unittest.main()
