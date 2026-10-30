import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kobold_rpg.engine import Engine,RuleError
from kobold_rpg.story_world import build_sketch,generate_world
from kobold_rpg.gm import record_changes,reply,reply_schema,decode_reply
from kobold_rpg.gm_context import recalled_context
from kobold_rpg.scene_memory import project
from kobold_rpg.portable import export_file,validate_file,validate_state
from kobold_rpg.library import CampaignLibrary
from kobold_rpg.campaign import blank_campaign
from test_library import fixture


def sketch():
    return {'central_conflict':'碼頭工程正在掩蓋失蹤案。','ending_conflict':'是否公開真相與如何處理代價，結果未定。',
        'truths':[{'id':f'truth_{i}','text':f'固定真相 {i}，失蹤者一直被關在水庫。'} for i in range(1,4)],
        'chapters':[{'id':f'chapter_{i}','title':f'方向 {i}','focus':'調查與日常都可自由選擇。','reveals':[f'truth_{i}']} for i in range(1,4)],
        'opening_lead':{'clue':'牆上公告的一行名字被劃去。','basis':'碼頭的公告隨工程名單更新。'}}


def expansion(**overrides):
    return {'chapter':'chapter_2','actors':[],'outcomes':['可調查，也可離開。'],
        'opportunities':[{'id':'water_mark','place':'start','carrier':'environment',
                         'clue':'門框上有一道舊水位刻痕。','basis':'這裡曾經淹水。'}],
        'evidence':'門框上有一道舊水位刻痕',**overrides}


class ProgressiveWorldTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=fixture();self.candidate=build_sketch(self.base,sketch())

    def engine(self):return Engine(Path(self.tmp.name)/'game.sqlite3',seed=self.candidate['seed'])

    def test_start_has_only_original_scene_and_fixed_truths_not_full_future_chapters(self):
        state=self.candidate['seed'];validate_state(state)
        self.assertEqual(state['npcs'],self.base['seed']['npcs'])
        self.assertEqual(state['locations'],self.base['seed']['locations'])
        chapters=state['story']['blueprint']['chapters']
        self.assertTrue(all(row['detail_status']=='outline' for row in chapters))
        self.assertEqual(chapters[1]['opportunities'],[])
        self.assertEqual(state['story']['blueprint']['truths'],sketch()['truths'])

    def test_skeleton_failure_resumes_base_but_successful_new_world_is_not_reused(self):
        folder=Path(self.tmp.name)/'drafts';prefs=self.base['preferences']
        with patch('kobold_rpg.story_world.generate_plan',return_value=self.base) as plan,\
             patch('kobold_rpg.story_world._complete',side_effect=[RuleError('interrupted'),sketch(),sketch()]):
            with self.assertRaises(RuleError):generate_world(prefs,'http://model',folder)
            self.assertEqual(len(list(folder.glob('*.json'))),1)
            generate_world(prefs,'http://model',folder)
            self.assertEqual(plan.call_count,1)
            self.assertEqual(list(folder.glob('*.json')),[])
            generate_world(prefs,'http://model',folder)
            self.assertEqual(plan.call_count,2)

    def test_checkpoint_is_not_reused_for_different_preferences_or_model(self):
        folder=Path(self.tmp.name)/'drafts'
        with patch('kobold_rpg.story_world.generate_plan',return_value=self.base) as plan,\
             patch('kobold_rpg.story_world._complete',side_effect=RuleError('interrupted')):
            for prefs,url in [(self.base['preferences'],'http://one'),({**self.base['preferences'],'wishes':'另一個故事'},'http://one'),(self.base['preferences'],'http://two')]:
                with self.assertRaises(RuleError):generate_world(prefs,url,folder)
            self.assertEqual(plan.call_count,3)

    def test_confirmation_and_portable_save_keep_lazy_outline_and_hide_secrets(self):
        library=CampaignLibrary(Path(self.tmp.name)/'library',Engine(Path(self.tmp.name)/'blank.sqlite3',seed=blank_campaign()))
        preview=library.preview(self.candidate)
        library.create(preview['preview_id'])
        payload=validate_file(export_file(library.engine))
        self.assertEqual(payload['state']['story']['generation'],'progressive')
        self.assertNotIn('固定真相',json.dumps(library.public_state(),ensure_ascii=False))
        self.assertEqual(library.engine.state()['revision'],1)

    def test_actual_contact_appends_details_and_can_record_the_new_offer_in_same_turn(self):
        engine=self.engine();before=engine.state();narration='門框上有一道舊水位刻痕。'
        engine.record_gm_reply('調查門框',{'narration':narration,'changes':{
            'story_expand':expansion(),'story_update':{'chapter':'chapter_2',
                'opportunities':{'water_mark':'presented'},'evidence':narration}}},'one',0)
        after=engine.state();story=after['story']
        self.assertEqual(story['blueprint']['truths'],before['story']['blueprint']['truths'])
        self.assertEqual(story['progress']['opportunities']['water_mark'],'presented')
        self.assertEqual(story['blueprint']['chapters'][1]['detail_status'],'developing')
        self.assertEqual(story['blueprint']['chapters'][2],before['story']['blueprint']['chapters'][2])
        validate_file(export_file(engine));self.assertTrue(engine.verify())

    def test_bad_expansion_does_not_drop_a_valid_player_action_or_change_truths(self):
        state=self.candidate['seed'];before=copy.deepcopy(state)
        after,status=record_changes(state,{'pc':{'equipment_notes':'已收起雨傘'},
            'story_expand':expansion(truths=[],opportunities=[])},1,'門框上有一道舊水位刻痕。')
        self.assertEqual(status,'ready');self.assertEqual(after['pc']['equipment_notes'],'已收起雨傘')
        self.assertEqual(after['story'],before['story']);self.assertEqual(state,before)

    def test_first_use_prepares_only_private_details_without_accepting_or_revealing_anything(self):
        state=self.candidate['seed'];truth=state['story']['blueprint']['truths'][0]
        plan=expansion(chapter='chapter_1',planning_truth=truth['id'],evidence=truth['text'])
        after,status=record_changes(state,{'story_expand':plan},1,'店主繼續閒聊天氣。')
        self.assertEqual(status,'ready')
        self.assertEqual(after['story']['progress'],state['story']['progress'])
        self.assertEqual(after['story']['blueprint']['truths'],state['story']['blueprint']['truths'])
        self.assertEqual(after['story']['blueprint']['chapters'][0]['detail_status'],'developing')
        schema=reply_schema(state)['properties']['establish']['properties']['chapter']
        self.assertEqual(schema['type'],'object')
        self.assertEqual(schema['properties']['evidence']['enum'],[truth['id']])
        self.assertIn('anyOf',reply_schema(after)['properties']['establish']['properties']['chapter'])

    def test_duplicate_offer_cannot_overwrite_rejected_clue(self):
        engine=self.engine();narration='公告上的名字已經劃去，今天不追查。'
        engine.record_gm_reply('不追查',{'narration':narration,'changes':{'story_update':{
            'opportunities':{'opening_lead':'declined'},'evidence':narration}}},'one',0)
        before=engine.state()
        for offer in [dict(before['story']['blueprint']['chapters'][0]['opportunities'][0]),
                      {**before['story']['blueprint']['chapters'][0]['opportunities'][0],'id':'reskinned'}]:
            after,status=record_changes(before,{'story_expand':expansion(opportunities=[offer])},2,'門框上有一道舊水位刻痕。')
            self.assertEqual(after['story'],before['story'])

    def test_expansion_cannot_move_an_existing_carrier_or_reopen_a_dead_actor(self):
        state=self.candidate['seed'];state['npcs']['guide']['alive']=False
        offer=expansion()['opportunities'][0];offer['carrier']='guide'
        after,_=record_changes(state,{'story_expand':expansion(opportunities=[offer])},1,'門框上有一道舊水位刻痕。')
        self.assertEqual(after['story'],state['story']);self.assertFalse(after['npcs']['guide']['alive'])

    def test_daily_chat_keeps_one_model_call_and_does_not_expand_chapters_by_turn_count(self):
        state=self.candidate['seed'];before=copy.deepcopy(state['story'])
        for i in range(5):
            with patch('kobold_rpg.model._complete',return_value={'narration':'店主談起今天的天氣。','changes':{}}) as model:
                result=reply(state,'今天只想閒聊。','http://model')
            model.assert_called_once();state,_=record_changes(state,result['changes'],i+1,result['narration'])
        self.assertEqual(state['story'],before)

    def test_typed_establishment_is_saved_before_dependent_character_interaction(self):
        state=self.candidate['seed'];person={'id':'dockhand','name':'灰帽船工（Grey Hat Dockhand）',
            'species':'人類','role':'船工','description':'戴灰帽的成年男人。','activity':'擦拭酒杯',
            'stance':'願意談談工作','concern':'明天的船期','knowledge':['自己的工作與船期']}
        raw={'player_power_uses':[],'establish':{'people':[person],'chapter':expansion()},
             'narration':'灰帽船工回答了問題，門框上有一道舊水位刻痕。','changes':{}}
        with patch('kobold_rpg.model._complete',return_value=raw) as model:
            result=reply(state,'我問這位船工的工作。','http://model')
        model.assert_called_once()
        engine=self.engine();engine.record_gm_reply('我問這位船工的工作。',result,'contact',0)
        after=engine.state();self.assertEqual(after['npcs']['dockhand']['role'],'船工')
        self.assertEqual(after['npcs']['dockhand']['detail_level'],'incidental')
        self.assertIn('dockhand',after['canon']['actors'])
        self.assertEqual(after['story']['blueprint']['chapters'][1]['detail_status'],'developing')
        validate_file(export_file(engine))

    def test_name_learned_in_same_reply_updates_the_new_person_without_a_second_record(self):
        state=self.candidate['seed'];person={'id':'npc_1_1','name':'灰帽船工（Grey Hat Dockhand）',
            'species':'人類','role':'船工','description':'戴灰帽的成年男人。','activity':'擦拭酒杯',
            'stance':'願意談談工作','concern':'明天的船期','knowledge':['自己的工作與船期']}
        raw={'establish':{'people':[person],'chapter':None},'narration':'船工說：「我叫艾倫（Ellen）。」',
             'changes':{'npcs':{'npc_1_1':{'name':'艾倫（Ellen）'},'npc_1_2':{'name':'不曾建立的個體'}}}}
        with patch('kobold_rpg.model._complete',return_value=raw):result=reply(state,'請問你的名字？','http://model')
        after,status=record_changes(state,result['changes'],1,result['narration'])
        self.assertEqual(status,'ready');self.assertEqual(after['npcs']['npc_1_1']['name'],'艾倫（Ellen）')
        self.assertNotIn('npc_1_2',after['npcs'])

    def test_pre_narrative_foundation_cannot_recreate_an_existing_person(self):
        state=self.candidate['seed'];before=copy.deepcopy(state['npcs']['guide'])
        person={'id':'guide','name':'另一個人（Someone Else）','species':'人類','role':'陌生人',
            'description':'不同外貌','activity':'不同活動','stance':'不同態度','concern':'不同牽掛','knowledge':[]}
        with patch('kobold_rpg.model._complete',return_value={'establish':{'people':[person],'chapter':None},
            'narration':'店主繼續整理店舖。','changes':{}}):result=reply(state,'看看店主。','http://model')
        after,_=record_changes(state,result['changes'],1,result['narration'])
        self.assertEqual(after['npcs']['guide']['name'],before['name'])
        self.assertEqual(after['npcs']['guide']['knowledge'],before['knowledge'])

    def test_truncated_tail_preserves_complete_foundations_and_power_checks_before_narration(self):
        header={'player_power_uses':[{'ability_id':'','manifested':False}],
            'establish':{'people':[],'chapter':None},'narration':'酒客回答了問題。'}
        raw=json.dumps(header,ensure_ascii=False)[:-1]+',"changes":{"npcs":'
        result=decode_reply(raw)
        self.assertEqual(result['narration'],header['narration'])
        self.assertEqual(result['establish'],header['establish'])
        self.assertEqual(result['player_power_uses'],header['player_power_uses'])
        self.assertEqual(result['changes'],{})

    def test_two_competing_complete_replies_do_not_supply_recovered_foundations(self):
        raw='{"establish":{"people":[],"chapter":null},"narration":"酒客回答了問題。"} {"narration":"另一個回答。"}'
        self.assertIsNone(decode_reply(raw)['establish'])


class SceneMemoryTests(unittest.TestCase):
    def setUp(self):
        self.state=fixture()['seed']
        people={f'guest_{i}':{'name':f'酒客甲{i}（Guest {i}）','description':f'坐在第{i}張桌邊的成年酒客。',
            'role':'船工','species':'人類','location':'start','detail_level':'incidental',
            'knowledge':['只有他自己知道的私密消息'+str(i)]} for i in range(60)}
        self.state,_=record_changes(self.state,{'npcs':people,'locations':{'start':{'crowd':'酒客們飲酒、打牌，並非每人都有任務。'}}},1)

    def test_large_crowd_loads_a_few_profiles_and_preserves_every_record_on_disk(self):
        before=copy.deepcopy(self.state);working=project(self.state,'看看酒館的情況。')
        self.assertLessEqual(len(working['npcs']),4);self.assertLessEqual(len(working['scene_people']),24)
        self.assertEqual(working['scene_scope']['present_count'],61)
        self.assertEqual(working['locations']['start']['crowd'],self.state['locations']['start']['crowd'])
        self.assertEqual(self.state,before)
        self.assertTrue(all('knowledge' not in npc for npc in working['scene_people'].values()))

    def test_named_archived_person_and_relevant_old_memory_are_retrieved(self):
        npc=self.state['npcs']['guest_35'];memories=[{'text':'答應明天在水庫交還紅色戒指。'}]
        memories.extend({'text':f'後來喝了第{i}杯酒。'} for i in range(15))
        npc['inner_life']['memories']=memories
        working=project(self.state,'我找酒客甲35，問水庫的紅色戒指。')
        self.assertIn('guest_35',working['npcs'])
        self.assertIn(memories[0],working['npcs']['guest_35']['inner_life']['memories'])
        self.assertEqual(len(npc['inner_life']['memories']),16)

    def test_model_returning_only_its_visible_memories_cannot_erase_the_archive(self):
        self.state['npcs']['guest_35']['inner_life']['memories']=['以前承諾歸還戒指。','後來喝酒。']
        after,status=record_changes(self.state,{'npcs':{'guest_35':{'inner_life':{'memories':['後來喝酒。','今天又見面。']}}}},2)
        self.assertEqual(status,'ready')
        self.assertEqual(after['npcs']['guest_35']['inner_life']['memories'],['以前承諾歸還戒指。','後來喝酒。','今天又見面。'])

    def test_a_selected_knowledge_patch_cannot_erase_older_known_information(self):
        before=self.state['npcs']['guest_35']['knowledge'][:]
        after,status=record_changes(self.state,{'npcs':{'guest_35':{'knowledge':['今天得知的新消息']}}},2)
        self.assertEqual(status,'ready')
        self.assertEqual(after['npcs']['guest_35']['knowledge'],[*before,'今天得知的新消息'])

    def test_older_structured_knowledge_entries_remain_portable_when_new_text_is_added(self):
        self.state['npcs']['guest_35']['knowledge']=[{'text':'較舊的已知資訊'}]
        after,status=record_changes(self.state,{'npcs':{'guest_35':{'knowledge':['今天得知的新消息']}}},2)
        self.assertEqual(status,'ready')
        self.assertEqual(after['npcs']['guest_35']['knowledge'],[{'text':'較舊的已知資訊'},'今天得知的新消息'])
        validate_state(after)

    def test_new_people_require_foundations_and_field_typos_are_not_generation_options(self):
        schema=reply_schema(self.state);people=schema['properties']['changes']['properties']['npcs']
        self.assertFalse(people['additionalProperties'])
        foundation=schema['properties']['establish']['properties']['people']['items']
        self.assertTrue({'name','description','species','role'}<=set(foundation['required']))
        self.assertFalse(foundation['additionalProperties'])
        self.assertIn('guest_35',people['properties'])
        self.assertNotIn('ordinary_capabilities',schema['properties']['player_power_uses']['items']['properties']['ability_id']['enum'])

    def test_narrated_fact_without_visibility_keeps_character_changes(self):
        after,status=record_changes(self.state,{'npcs':{'guest_35':{'encounter':{'stance':'願意談工作'}}},
            'facts_add':[{'text':'他說自己是船工。','kind':'said'}]},2)
        self.assertEqual(status,'ready');self.assertEqual(after['facts'][-1]['visibility'],'public')
        self.assertEqual(after['npcs']['guest_35']['encounter']['stance'],'願意談工作')

    def test_explicit_multiple_people_are_not_hidden_by_the_default_profile_limit(self):
        working=project(self.state,' '.join('酒客甲'+str(i) for i in range(10)))
        self.assertTrue({f'guest_{i}' for i in range(10)}<=set(working['npcs']))

    def test_small_context_reduces_the_working_set_without_erasing_any_people(self):
        state=copy.deepcopy(self.state)
        def measured(url,messages):
            snapshot=json.loads(messages[0]['content'].split('本回合狀態資料：\n')[1].split('\n\n主持與輸出要求')[0])
            return 9000 if len(snapshot['current_snapshot']['npcs'])>2 else 5000
        with patch('kobold_rpg.context_budget.budget',return_value=6000),patch('kobold_rpg.context_budget.count',side_effect=measured),\
             patch('kobold_rpg.model._complete',return_value={'narration':'酒客們繼續閒聊。','changes':{}}) as model:
            reply(state,'看看酒館。','http://mock')
        model.assert_called_once()
        snapshot=json.loads(model.call_args.args[0][0]['content'].split('本回合狀態資料：\n')[1].split('\n\n主持與輸出要求')[0])
        self.assertEqual(len(snapshot['current_snapshot']['npcs']),2)
        self.assertEqual(state,self.state)

    def test_evidenced_memory_is_private_and_incidental_person_can_develop_without_reset(self):
        state=self.state;narration='酒客甲35說：「明天我會把紅色戒指還給你。」'
        after,status=record_changes(state,{'npcs':{'guest_35':{'detail_level':'developed','memory_note':{
            'text':'答應明天交還紅色戒指。','evidence':'明天我會把紅色戒指還給你'}}},'scene_focus':['guest_35']},2,narration)
        self.assertEqual(status,'ready');npc=after['npcs']['guest_35']
        self.assertEqual(npc['knowledge'],state['npcs']['guest_35']['knowledge'])
        self.assertEqual(npc['inner_life']['memories'][-1]['text'],'答應明天交還紅色戒指。')
        self.assertNotIn('memory_note',npc)
        self.assertEqual(after['scene_memory']['focus']['start'][0],'guest_35')

    def test_older_exchange_is_recalled_after_many_other_conversations_and_survives_save(self):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'crowd.sqlite3',seed=fixture()['seed'])
            npc=self.state['npcs']['guest_35']
            engine.record_gm_reply('問酒客甲35戒指在哪',{'narration':'酒客甲35答應明天交還紅色戒指。',
                'changes':{'npcs':{'guest_35':npc},'scene_focus':['guest_35']}},'ring',0)
            for i in range(8):engine.record_gm_reply('我在別處閒聊',{'narration':'遠處傳來談笑聲。','changes':{}},str(i),i+1)
            state=engine.state();before=copy.deepcopy(state)
            recalled=recalled_context(engine,state,'我回頭找酒客甲35，問紅色戒指。',exclude=[6,7,8,9])
            self.assertEqual(recalled[0]['revision'],1);self.assertIn('紅色戒指',recalled[0]['narration'])
            self.assertEqual(engine.state(),before)
            self.assertNotIn('scene_memory',engine.public_state())
            self.assertEqual(validate_file(export_file(engine))['state']['scene_memory'],state['scene_memory'])
