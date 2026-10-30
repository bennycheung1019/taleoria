import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from kobold_rpg.campaign import blank_campaign,new_campaign
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.gm import reply
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.portable import export_file,validate_file
from kobold_rpg.story_world import build_story,generate_world
from kobold_rpg.story_director import context
from test_library import fixture


def story_fixture():
    base=fixture()
    sites=[{'id':'story_place_1','name':'堤岸醫館（Levee Clinic）','description':'岸邊固定的一間木造醫館。',
            'connects_to':'near_1','route_basis':'河岸小路沿堤岸通到醫館。'},
           {'id':'story_place_2','name':'河務所（River Office）','description':'河務員保存契約與水位紀錄的地方。',
            'connects_to':'start','route_basis':'店門外的街道連到河務所。'}]
    cast=[]
    for i,name,role in ((1,'莉娜（Lina）','成年醫師'),(2,'周文（Zhou Wen）','成年河務官')):
        cast.append({'id':f'story_actor_{i}','name':name,'species':'人類','role':role,'description':'一名穿素色外衣的成年人。',
            'personality':'細心務實，有自己的顧慮。','values':'維持穩定生活。','concern':'水路改建影響當地生計。',
            'boundary':'不交出私人文件。','levers':'可查證的理由與實際協助。','activity':'正在整理工作文件。',
            'location':f'story_place_{i}','powers':[]})
    chapters=[]
    for i in range(1,4):
        chapters.append({'id':f'chapter_{i}','title':f'章節 {i}','focus':'逐步查明水路改建的利益衝突。',
            'reveals':[f'truth_{i}'],'actors':['guide','story_actor_1','story_actor_2'],
            'outcomes':['取得線索，也可以不理會。','失去文件，但後果保留。'],
            'opportunities':[{'id':f'lead_{i}_a','place':'start','carrier':'guide','clue':'店主提到一份未能送達的河務清單。','basis':'河務所改建影響店主的運貨。'},
                {'id':f'lead_{i}_b','place':'near_1','carrier':'environment','clue':'河岸上有固定水位刻痕，與公告不符。','basis':'實際河況與河務所公告的差異。'}]})
    outline={'central_conflict':'水路改建背後的利益衝突，玩家可介入或繼續生活。','ending_conflict':'公開賬目、協商、合作或離開，結果由遊玩決定。',
        'truths':[{'id':f'truth_{i}','text':f'未公開的核心真相 {i}。'} for i in range(1,4)],
        'sites':sites,'cast':cast,'chapters':chapters,'opening':base['plan']['opening']}
    return base,outline


class StoryDirectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base,outline=story_fixture();self.candidate=build_story(base,outline)
        self.engine=Engine(Path(self.tmp.name)/'story.sqlite3',seed=self.candidate['seed'])

    def turn(self,narration,changes=None):
        rev=self.engine.state()['revision']
        return self.engine.record_gm_reply('我自由選擇接下來的行動。',{'narration':narration,'changes':changes or {}},str(rev),rev)

    def test_fixed_actors_places_and_personality_are_established_before_opening_but_not_public(self):
        state=self.engine.state()
        self.assertFalse(state['npcs']['story_actor_1']['known'])
        self.assertEqual(state['npcs']['story_actor_1']['location'],'story_place_1')
        self.assertEqual(state['canon']['actors']['story_actor_1']['established_revision'],0)
        self.assertEqual(state['pc']['spells'],[])
        public=json.dumps(self.engine.public_state(),ensure_ascii=False)
        for secret in ('未公開的核心真相','莉娜','周文','story_place_1','central_conflict'):
            self.assertNotIn(secret,public)

    def test_opportunities_have_a_real_location_and_do_not_teleport_their_carrier(self):
        state=self.engine.state();before=copy.deepcopy(state)
        offered=context(state)['opportunities']
        self.assertEqual([item['id'] for item in offered],['lead_1_a'])
        self.assertEqual(state,before)
        state['pc']['location']='near_1'
        self.assertEqual([item['id'] for item in context(state)['opportunities']],['lead_1_b'])
        self.assertEqual(state['npcs']['guide']['location'],'start')

    def test_declined_lead_is_not_reskinned_or_reoffered_after_cooldown(self):
        self.turn('店主提到河務清單，你暫時沒有追查。',{'story_update':{
            'opportunities':{'lead_1_a':'declined'},'evidence':'店主提到河務清單'}})
        for _ in range(5):self.turn('你繼續在店裡整理藥草。')
        self.assertEqual(context(self.engine.state())['opportunities'],[])

    def test_presented_clue_has_a_quiet_period_and_is_remembered_without_repeating(self):
        self.turn('店主提到河務清單，需要有人查證。',{'story_update':{
            'opportunities':{'lead_1_a':'presented'},'evidence':'店主提到河務清單'}})
        state=self.engine.state();state['pc']['location']='near_1'
        self.assertEqual(context(state)['opportunities'],[])
        self.assertEqual(context(state)['established_threads'][0]['id'],'lead_1_a')

    def test_npc_death_and_early_ending_are_not_undone_to_preserve_chapters(self):
        truth=copy.deepcopy(self.engine.state()['story']['blueprint']['truths'])
        self.turn('河務官已死亡，衝突以這個結果告一段落。',{'npcs':{'story_actor_2':{'alive':False}},
            'story_update':{'chapter':'chapter_3','status':'resolved','evidence':'衝突以這個結果告一段落'}})
        state=self.engine.state();self.assertFalse(state['npcs']['story_actor_2']['alive'])
        self.assertEqual(state['story']['blueprint']['truths'],truth)
        self.assertEqual(context(state)['opportunities'],[])
        self.assertFalse(context(state)['actor_reality']['story_actor_2']['alive'])

    def test_missing_optional_progress_proof_never_blocks_an_ordinary_action(self):
        self.turn('你走到河岸小路。',{'pc':{'location':'near_1'},'story_update':{'chapter':'chapter_3','evidence':'不存在於回覆的句子'},
            'story':{'blueprint':{'truths':[]}}})
        state=self.engine.state();self.assertEqual(state['pc']['location'],'near_1')
        self.assertEqual(state['story']['progress']['chapter'],'chapter_1')
        self.assertEqual(len(state['story']['blueprint']['truths']),3)
        self.assertTrue(self.engine.verify())

    def test_save_load_keeps_private_outline_choices_and_consequences(self):
        self.turn('水位公告與刻痕不符，第一項真相已被查明。',{'story_update':{
            'revealed':['truth_1'],'chapter':'chapter_2','evidence':'水位公告與刻痕不符'}})
        payload=validate_file(export_file(self.engine))
        library=CampaignLibrary(Path(self.tmp.name)/'library',Engine(Path(self.tmp.name)/'blank.sqlite3',seed=blank_campaign()))
        library.import_file(payload)
        self.assertEqual(library.engine.state()['story'],self.engine.state()['story'])
        self.assertNotIn('story',library.public_state())

    def test_normal_turn_keeps_one_model_call_and_the_original_input(self):
        original='我今天只想整理店舖，不想查案。'
        with patch('kobold_rpg.model._complete',return_value={'player_power_uses':[],'narration':'店裡的藥草散發淡香。','changes':{}}) as model:
            reply(self.engine.state(),original,'http://model')
        model.assert_called_once()
        messages=model.call_args.args[0]
        self.assertEqual(messages[-1]['content'],original)
        self.assertIn('story_director',messages[0]['content'])
        self.assertIn('RPG OS v1.01',messages[0]['content'])

    def test_preestablished_unmet_actor_is_available_to_the_gm_when_player_arrives(self):
        state=self.engine.state();state['pc']['location']='story_place_1'
        with patch('kobold_rpg.model._complete',return_value={'narration':'醫館內有人整理文件。','changes':{}}) as model:
            reply(state,'看看醫館裡有甚麼人。','http://model')
        self.assertIn('莉娜',model.call_args.args[0][0]['content'])
        self.assertFalse(state['npcs']['story_actor_1']['known'])

    def test_fresh_install_has_no_old_characters_or_fake_campaign_entries(self):
        blank=Engine(Path(self.tmp.name)/'new.sqlite3',seed=blank_campaign())
        library=CampaignLibrary(Path(self.tmp.name)/'fresh-library',blank)
        self.assertEqual(library.list(),{'campaigns':[],'saves':[]})
        self.assertEqual(library.public_state()['npcs'],{})
        self.assertTrue(library.public_state()['setup_required'])

    def test_confirmation_uses_established_seed_without_old_approval_pipeline(self):
        blank=Engine(Path(self.tmp.name)/'new.sqlite3',seed=blank_campaign())
        library=CampaignLibrary(Path(self.tmp.name)/'confirm-library',blank)
        preview=library.preview(self.candidate)
        self.assertNotIn('truths',json.dumps(preview))
        with patch.object(Engine,'propose',side_effect=AssertionError('no extra referee')):
            library.create(preview['preview_id']);library.create(preview['preview_id'])
        self.assertEqual(library.engine.state()['revision'],1)
        self.assertEqual(len(library.engine.history()),1)
        self.assertIn('story',library.engine.state())

    def test_creation_adds_only_a_short_skeleton_call_and_no_remote_cast(self):
        base,old=story_fixture()
        outline={key:old[key] for key in ('central_conflict','ending_conflict','truths')}
        outline['chapters']=[{key:row[key] for key in ('id','title','focus','reveals')} for row in old['chapters']]
        outline['opening_lead']={'clue':'河務公告有一處墨跡被刮去。','basis':'店外牆上原有河務公告。'}
        with patch('kobold_rpg.story_world.generate_plan',return_value=base) as plan,patch('kobold_rpg.story_world._complete',return_value=outline) as model:
            result=generate_world(base['preferences'],'http://model')
        model.assert_called_once();self.assertEqual(result['source_mode'],'rpg_os_progressive')
        self.assertTrue(plan.call_args.kwargs['compact'])
        self.assertEqual(model.call_args.args[2],1200)
        self.assertEqual(set(result['seed']['npcs']),set(base['seed']['npcs']))
        self.assertEqual(set(result['seed']['locations']),set(base['seed']['locations']))
        self.assertIsNone(result['audit'])

    def test_token_budget_preserves_os_and_latest_exchange_with_matching_history_index(self):
        recent=[{'revision':i,'declaration':'舊問題'+str(i),'narration':'舊答案'+str(i),'location':'start','witnesses':['guide']} for i in range(1,5)]
        def count(_url,messages):return 9000 if len(messages)>4 else 5000
        with patch('kobold_rpg.context_budget.budget',return_value=6000),patch('kobold_rpg.context_budget.count',side_effect=count),\
             patch('kobold_rpg.model._complete',return_value={'narration':'這次的回答。','changes':{}}) as model:
            reply(self.engine.state(),'這次的新問題？','http://mock',recent=recent)
        model.assert_called_once();messages=model.call_args.args[0]
        self.assertEqual([row['role'] for row in messages],['system','user','assistant','user'])
        self.assertEqual(messages[1]['content'],'舊問題4')
        self.assertIn('SOURCE: OS/LAW.md',messages[0]['content'])
        snapshot=messages[0]['content'].split('本回合狀態資料：\n')[1].split('\n\n主持與輸出要求')[0]
        self.assertEqual(json.loads(snapshot)['history_index'][0]['revision'],4)
        self.assertEqual(len(recent),4)

    def test_own_starting_powers_appear_on_character_sheet_without_revealing_npc_powers(self):
        state=self.engine.state()
        from kobold_rpg.canon import establish
        establish(state,{'kind':'power','id':'light','actor':state['pc']['id'],'name':'微光術','effect':'照亮掌心',
            'requires_flags':[],'result_form':None},'角色建立時已學會',0,RuleError)
        public=self.engine.public_state(state,[])
        self.assertEqual(public['pc']['known_powers'][0]['name'],'微光術')

    def test_small_context_keeps_latest_exchange_by_reserving_a_shorter_reply(self):
        recent=[{'revision':2,'declaration':'剛才的問題','narration':'剛才的回答'}]
        with patch('kobold_rpg.context_budget.budget',side_effect=lambda url,maximum:8192-maximum-128),\
             patch('kobold_rpg.context_budget.count',side_effect=lambda url,messages:6700 if len(messages)>2 else 6300),\
             patch('kobold_rpg.model._complete',return_value={'narration':'回答這次問題。','changes':{}}) as model:
            reply(self.engine.state(),'接著呢？','http://mock',recent=recent)
        self.assertEqual(len(model.call_args.args[0]),4)
        self.assertEqual(model.call_args.args[2],1200)

    def test_all_fixed_truths_remain_available_when_exploring_off_chapter(self):
        state=self.engine.state()
        self.assertEqual(context(state)['fixed_truths'],state['story']['blueprint']['truths'])

    def test_adjacent_established_characters_are_retrieved_before_arrival(self):
        state=self.engine.state()
        with patch('kobold_rpg.model._complete',return_value={'narration':'你沿路走近。','changes':{}}) as model:
            reply(state,'前往附近看看。','http://mock')
        snapshot=model.call_args.args[0][0]['content'].split('本回合狀態資料：\n')[1].split('\n\n主持與輸出要求')[0]
        data=json.loads(snapshot)['current_snapshot']
        self.assertIn('story_actor_2',data['nearby_characters'])
        self.assertFalse(state['npcs']['story_actor_2']['known'])


if __name__=='__main__':unittest.main()
