"""Explicit fresh-world establishment; no old Lite story is imported."""
from .engine import initial_state, RuleError
from .canon import establish


def blank_campaign():
    """An onboarding shell; no previous story or characters are seeded."""
    state=initial_state()
    state['setup_required']=True
    state['contract'].update(title='建立你的新故事',genre='尚未建立',difficulty='一般',permadeath=False,
        canon_policy='RPG OS v1.01 主導世界建立與遊戲裁定')
    state['pc'].update(id='player',name='旅人（Traveller）',location='start',capabilities=[],goal='尚未建立')
    state['locations']={'start':{'name':'尚未建立（Not Yet Created）','description':'先建立世界，再開始你的冒險。','exits':{}}}
    state['npcs']={};state['facts']=[]
    state['world']={'background':'','rules':[]};state['item_catalog']={}
    return state


def new_campaign():
    state = initial_state()
    state['contract'].update(title='霧橋鎮：雨中的渡口', canon_policy='身分與超自然原因先建立，後裁定；不以結果倒造原因')
    state['pc']['inventory'] = {'hunting_knife': 1, 'rain_cloak': 1, 'rope': 1}
    state['pc']['equipment_notes'] = '普通獵刀、雨斗篷與一捆繩索；沒有魔法效果。'
    state['locations']['gate'].update(name='霧橋鎮北門', description=
        '暮雨打在北門的石拱上。門洞通向鎮內的河街，右邊沿外牆幾步便是避雨棚；河街盡頭能看見渡口的桅杆。'
        '門燈已點亮，哈克站在燈下核對一張被雨水打濕的交班紙。門外道路暫無可見阻礙。')
    state['locations']['shelter']['description'] = '木棚緊靠霧橋鎮北門，棚下有一張空長凳。門燈及哈克仍在視線內。'
    state['locations']['gate']['exits']['river_street'] = {'known': True, 'clear': True}
    state['locations']['river_street'] = {'name': '河街', 'description':
        '石板河街沿北門通向渡口，左側的麵包店已掛起歇業木牌，屋簷下可避雨。渡口的安雅正在整理繫船索。',
        'exits': {'gate': {'known': True, 'clear': True}, 'pier': {'known': True, 'clear': True}}}
    state['locations']['pier'] = {'name': '渡口', 'description':
        '渡船繫在木樁旁，雨水把木板浸得發亮。安雅在棚邊整理繩索，河街通向北門。渡船尚未開航。',
        'exits': {'river_street': {'known': True, 'clear': True}}}
    hark = state['npcs']['hark']
    hark['description'] = '哈克（Hark）是一名成年男性人類守衛，披雨斗篷、佩普通短劍，正在門燈下查看交班紙。'
    hark['anchor']['concern'] = '接班人遲到，弟弟又在家等他；希望先找到可信的交接安排'
    hark['encounter']['priorities'] = '弄清交班延誤，兼顧門口秩序與回家照顧弟弟'
    hark['inner_life'] = {'personality': {'description': '務實、略帶乾幽默，重視責任，也容易被實際的體貼打動；不輕信陌生人的空話。',
        'basis': '新戰役開場先行建立', 'established_revision': 0}, 'limits': [], 'current_emotions': [],
        'relationships': {}, 'memories': [], 'personality_history': []}
    state['npcs']['anya'] = {'id': 'anya', 'name': '安雅（Anya）', 'location': 'pier', 'known': True, 'alive': True,
        'description': '安雅（Anya）是一名成年女性人類船主，穿厚外套，正在渡口整理普通繫船索。',
        'anchor': {'values': '獨立經營渡船，讓常客與貨物安全過河', 'concern': '雨勢未停，需要確認河流狀況才決定是否開航',
                   'boundary': '不願讓別人擅自碰她的船或替她決定航程', 'levers': '尊重她的專業、可靠消息及實際協助'},
        'encounter': {'condition': '清醒、雙手沾水，正在整理繫船索', 'priorities': '先把船繫穩，再查看河況',
                      'appraisal': '尚未與班交談，不知道他的目的', 'attraction': '尚未建立對班的吸引或排斥', 'stance': '可交談，未答應載客或提供協助'},
        'knowledge': ['本地渡口與自己的渡船'], 'conditions': [],
        'inner_life': {'personality': {'description': '直率、自主，喜歡細心又有幽默感的人；遇到不尊重時會堅定維護界線。',
            'basis': '新戰役開場先行建立', 'established_revision': 0}, 'limits': [], 'current_emotions': [],
            'relationships': {}, 'memories': [], 'personality_history': []}}
    state['canon'] = {'version': 1, 'actors': {}, 'powers': {}, 'flags': {}, 'uses': []}
    for who, role in [('ben', '成年男性邊境獵巫者'), ('hark', '成年男性北門守衛'), ('anya', '成年女性渡船船主')]:
        establish(state, {'kind': 'identity', 'actor': who, 'species': '人類', 'role': role,
                         'forms': {'human': '普通人類身體，無超自然外觀'}, 'current_form': 'human'},
                  '霧橋鎮新戰役開場設定；在首次敘事前建立', 0, RuleError)
    state['facts'] = [{'text': '目前已建立人物皆為人類；無已學法術、變身、詛咒或魔法物品。這不否定世界其他地方日後可先行建立的超自然現象。',
                       'visibility': 'private', 'source': 'new-campaign:0'}]
    return state
