import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import new_campaign
from kobold_rpg.engine import Engine
from kobold_rpg.gm import reply
from kobold_rpg.gm_context import recent_context


class GMContextTests(unittest.TestCase):
    def setUp(self):
        self.state=new_campaign();self.state['pc']['location']='pier'

    def test_history_uses_paired_chat_roles_and_current_input_is_alone(self):
        past=[{'revision':1,'location':'pier','witnesses':['anya'],'bookkeeping':'ready',
               'declaration':'請問船費？','narration':'安雅答：「單程三枚銅幣。」'},
              {'revision':2,'location':'pier','witnesses':['anya'],'bookkeeping':'ready',
               'declaration':'船幾點開？','narration':'安雅看著河面：「雨小些就開。」'}]
        original='咁小朋友收幾多錢？';before=copy.deepcopy((self.state,past))
        provenance={'snapshot_revision':2,'field_history':{'npcs.anya.encounter.stance':{'last_changed_revision':1}}}
        with patch('kobold_rpg.model._complete',return_value={'narration':'安雅答：「小朋友半價。」','changes':{}}) as model:
            reply(self.state,original,'http://local',recent=past,state_provenance=provenance)
        model.assert_called_once();messages=model.call_args.args[0]
        self.assertEqual([message['role'] for message in messages],['system','user','assistant','user','assistant','user'])
        self.assertEqual(messages[-1],{'role':'user','content':original})
        self.assertEqual(messages[1]['content'],past[0]['declaration'])
        self.assertEqual(messages[2]['content'],past[0]['narration'])
        self.assertEqual(messages[3]['content'],past[1]['declaration'])
        self.assertEqual(messages[4]['content'],past[1]['narration'])
        snapshot=json.loads(messages[0]['content'].split('本回合狀態資料：\n',1)[1].split('\n\n主持與輸出要求：',1)[0])
        self.assertEqual(snapshot['state_provenance'],provenance)
        self.assertEqual(snapshot['current_snapshot']['pc']['role'],self.state['canon']['actors']['ben']['role'])
        self.assertEqual(snapshot['history_index'][0]['witnesses'],['anya'])
        self.assertNotIn('narration',snapshot['history_index'][0])
        self.assertNotIn('recent_story',snapshot)
        self.assertEqual((self.state,past),before)

    def test_repeated_model_reply_is_not_blocked_retried_or_rewritten(self):
        old='安雅說：「等雨小些就開。」'
        with patch('kobold_rpg.model._complete',return_value={'narration':old,'changes':{}}) as model:
            result=reply(self.state,'我想再問一次船期','http://local',recent=[{'declaration':'幾時開？','narration':old}])
        self.assertEqual(model.call_count,1)
        self.assertEqual(result['narration'],old)

    def test_field_dates_come_from_real_state_changes_not_model_supplied_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=self.state)
            engine.record_gm_reply('幾時開船？',{'narration':'安雅回答雨小些就開。',
                'changes':{'npcs':{'anya':{'encounter':{'stance':'等候雨勢減弱'},
                                      'inner_life':{'personality':{'established_revision':900}}}}}},'first',0)
            engine.record_gm_reply('過河幾錢？',{'narration':'安雅答單程三枚銅幣。',
                'changes':{'npcs':{'anya':{'encounter':{'condition':'已回答船費，正留意河面'}}}}},'second',1)
            state=engine.state();before=copy.deepcopy(engine.history())
            recent,provenance=recent_context(engine,state)
            self.assertEqual([row['revision'] for row in recent],[1,2])
            fields=provenance['field_history']
            self.assertEqual(fields['npcs.anya.encounter.stance'],{'last_changed_revision':1})
            self.assertEqual(fields['npcs.anya.encounter.condition'],{'last_changed_revision':2})
            self.assertEqual(fields['npcs.anya.inner_life.personality'],{'last_changed_revision':1})
            self.assertEqual(fields['locations.pier.description'],{'last_changed_revision':0})
            self.assertEqual(engine.state(),state);self.assertEqual(engine.history(),before)
            _,limited=recent_context(engine,state,scan=1)
            self.assertEqual(limited['field_history']['locations.pier.description'],{'last_changed_before_revision':2})

    def test_metadata_only_revision_is_not_replayed_as_a_player_turn(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'world.sqlite3',seed=self.state)
            engine.record_gm_reply('你好',{'narration':'安雅點頭。','changes':{}},'hello',0)
            state=engine.state()
            with engine.connect() as db:
                engine._append(db,state,copy.deepcopy(state),'maintenance',{'status':'enrichment',
                    'action':{'kind':'freeform','text':'【資料整理】'},'narration':'','events':[]})
            recent,_=recent_context(engine,engine.state())
            self.assertEqual(len(recent),1);self.assertEqual(recent[0]['declaration'],'你好')


if __name__=='__main__':unittest.main()
