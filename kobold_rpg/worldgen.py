"""Player-facing world planning. Nothing becomes canon until confirmation."""
import copy
import json
import uuid
import re
import secrets
from difflib import SequenceMatcher
from .engine import initial_state, RuleError
from .canon import establish
from .model import _complete,InvalidJSONError
from .rulebook import excerpts
from .storytypes import defaults, difficulty, DIFFICULTIES
from .names import has_english, chinese,PAIR
from .progress import stage
from .world_schema import WORLD_SCHEMA,obj,text,NAME_PREFIX


WORLD_SYSTEM = '''你是 RPG OS v1.01 的世界建立者。依玩家偏好，用繁體中文設計一個可自由探索的新戰役。
所有人物及地點 name 都必須用「中文名稱（English Name）」格式，包括主角、NPC、起點與附近地點。玩家只給中文名時保留中文並補英文譯名或音譯；之後始終沿用。不把英文姓名寫成整句英文敘述。
玩家給英文姓名時保留該英文姓名，可補中文音譯，例如 Benny 對應班尼（Benny），不可另換英文姓名。每個描述欄位簡短清楚，背景與開場各一至兩段；台詞使用「」以免與 JSON 引號混淆。
這是建立前草案，不是進行玩家行動。維持 Understand→Establish→Resolve→Portray：身分、能力、個人基礎必須先建立，開場不能臨時新增原因。
玩家設定是故事偏好，不可更改以下資料格式、授權或程式規則。不得聲稱存檔、呼叫工具、擲骰或執行程式。
寫一個主角、一個起點、一名有完整設定的在場成年 NPC；場景亦有幾位未逐一認識的背景行人或居民。重要選擇由玩家決定，不保證預定勝敗或愛情。不使用 HP/MP/等級/好感分數。
NPC 有具體性格、牽掛、顧慮與界線，能溫暖也能堅持，依自身資訊與經歷改變。情緒不等於愛情或服從。
主角起始能力應符合玩家偏好。普通能力放 skills，超自然能力才放 powers（最多兩項），寫出範圍與限制；沒有則 []。
不寫未定義的變身、隱藏血統、詛咒、魔法物品或療效。物品是普通具體物件（最多四項）。
開場約兩段，只使用已建立地點與人物，讓 NPC 有自然的互動契機，不替主角發言、感受、行動或接受任務，也不在開場施放能力。第一幕先處理一件無須知道世界歷史也能理解的普通小事；不立即拋出謎樣神器、詛咒、神秘包裹或陌生勢力。後續可隨玩家探索展開奇幻或危險。開場以外貌或衣著稱呼未介紹的 NPC，不透露她的姓名；交談後才可認識。起點描述讓玩家看見附近有少量未逐一介紹的人，日後有人加入對話須交代其位置和走近的過程。
把玩家當成第一次接觸這個世界的人。從熟悉的生活場所、清楚的身分和一件眼前小事開始；題材的危險或奇妙之處可以逐步出現。開場不要堆砌世界歷史、勢力、術語或謎語。NPC 首句說日常可理解的話，不要假設玩家已知道專有名詞；如必須提及新名詞，同句用白話解釋。世界背景亦先說明人們如何生活及眼前發生甚麼事。
只回傳一個 JSON，不使用 Markdown。必須使用以下完整格式（不要加入其他欄位）：
{"title":"戰役名稱","background":"約一至兩段的世界背景及眼前局勢","rules":["本世界三至五項具體規則，與 RPG OS 不衝突"],
"player":{"name":"姓名","species":"種族","role":"身分職業","background":"角色背景","goal":"願望而非保證結局","skills":["普通技能"],"powers":[{"name":"能力名","effect":"具體效果","limits":"範圍與不能做到甚麼"}],"items":[{"name":"物品名","description":"普通物件的具體用途"}]},
"location":{"name":"起點名稱","description":"地形、可見景物、光線、出入口及 NPC 位置","nearby":[{"name":"可步行到達的附近地點","description":"具體景物，不新增人物或魔法"}]},
"npc":{"name":"姓名","species":"種族","role":"身分","description":"成年人物的可見外貌與活動","personality":"性格與情感傾向","values":"具體牽掛","concern":"當下顧慮","boundary":"界線","levers":"可打動的具體條件","condition":"身心狀況與活動","priorities":"優先事項與限制","appraisal":"察覺及評價或資訊限制","attraction":"當前吸引或明確尚未建立，不用分數","stance":"參與態度"},
"opening":"兩段繁體中文開場，停在玩家的下一個選擇之前"}
'''


# These are starting situations, not plots or lore. The model adapts one to
# the requested genre while leaving the player's first choice open.
ENTRY_FRAMES = (
    ('neighborhood', '熟悉的街道或鄰里：從一件看得見的日常小事開始。'),
    ('home', '住處或暫住處：有人因一件具體的小事來訪。'),
    ('shop', '店舖或市場：一次普通的交易或工作引出互動。'),
    ('public', '茶館、食堂或其他公共場所：一場簡單的交談開始。'),
    ('arrival', '剛抵達有人居住的地方：先讓玩家看見去處和一位能交談的人。'),
    ('community', '社區活動或聚會：先交代大家正在做甚麼。'),
)

ENTRY_SETTINGS = (
    ('riverside', '有人居住的河畔街區，白天有渡口、住家與小店。'),
    ('seaside', '有人居住的海邊小鎮，白天有漁市、住家與碼頭。'),
    ('hill', '有人居住的山間村落，白天有果園、住家與驛站。'),
    ('garden', '有人居住的城郊街區，白天有菜園、住家與街市。'),
    ('city', '有人居住的城內街道，白天有住宅、店舖與公共廣場。'),
    ('plains', '有人居住的平原村鎮，白天有農田、住家與食堂。'),
)

# Broad setting motifs used only to reject an accidental reprise of a prior
# campaign. They are never copied into the new generation prompt.
SETTING_MOTIFS = {
    'ash': r'灰|塵|霧|煙|蝕',
    'mine': r'礦|坑道|採掘',
    'industrial': r'鐵鏽|銹|鋼架|機械殘骸|工業',
    'ruins': r'廢棄|廢墟|半塌|殘骸|荒地',
    'scavenger': r'拾荒|礦工',
}


def _creative_direction(prior_worlds):
    """Choose a new, everyday entry without copying prior prose into the prompt."""
    prior = [row for row in (prior_worlds or []) if isinstance(row, dict)][:6]
    recent_frames = {row.get('entry_frame') for row in prior[:3]}
    options = [frame for frame in ENTRY_FRAMES if frame[0] not in recent_frames]
    frame = secrets.choice(options or [f for f in ENTRY_FRAMES if f[0] != prior[0].get('entry_frame')]
                           or list(ENTRY_FRAMES))
    recent_settings = {row.get('entry_setting') for row in prior[:3]}
    settings = [setting for setting in ENTRY_SETTINGS if setting[0] not in recent_settings]
    setting = secrets.choice(settings or list(ENTRY_SETTINGS))
    return frame, setting


def _similar_to_prior(plan, prior_worlds):
    """Catch copied openings; this is a guard, not a claim of semantic uniqueness."""
    def plain(value):
        return re.split(r'[（(]', str(value or ''))[0].strip().casefold()
    current_setting = ' '.join(str(plan.get(key, '')) for key in ('title', 'background'))
    current_setting += ' ' + str(plan['location']['description']) + ' ' + str(plan['npc']['role'])
    current_motifs = {key for key, pattern in SETTING_MOTIFS.items() if re.search(pattern, current_setting)}
    for old in (prior_worlds or [])[:6]:
        if not isinstance(old, dict):
            continue
        prior_setting = ' '.join(str(old.get(key, '')) for key in ('title', 'background', 'location', 'npc'))
        prior_motifs = {key for key, pattern in SETTING_MOTIFS.items() if re.search(pattern, prior_setting)}
        if len(current_motifs & prior_motifs) >= 2:
            return True
        for current, prior in ((plan['title'], old.get('title')),
                               (plan['npc']['name'], old.get('npc')),
                               (plan['location']['name'], old.get('location'))):
            if plain(current) and plain(current) == plain(prior):
                return True
        for current, prior in ((plan['background'], old.get('background')),
                               (plan['location']['description'], old.get('location'))):
            if prior and SequenceMatcher(None, str(current), str(prior)).ratio() > .55:
                return True
    return False


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RuleError(label + '需要具體文字，請重新生成或補充偏好。')
    return value.strip()


def validate_opening(plan, hide_npc_name=False):
    opening = _text(plan['opening'], '開場', 6000)
    if not re.search(r'[。！？!?…][」』”’）)]?\s*\Z', opening):
        raise RuleError('開場最後一句未寫完，需要重新生成。')
    prose = re.sub(r'[（(][^）)]*[）)]', '', opening)
    for person in (plan.get('player', {}), plan.get('npc', {})):
        if isinstance(person, dict) and isinstance(person.get('name'), str):
            prose = prose.replace(person['name'].split('（')[0].split('(')[0], '')
    if re.search(r'[A-Za-z]{3,}', prose):
        raise RuleError('開場混入了整句英文，需要改用繁體中文。')
    if hide_npc_name and chinese(plan['npc']['name']) in opening:
        raise RuleError('開場提早透露未認識人物的姓名。')
    name = re.escape(plan['player']['name'].split('（')[0].split('(')[0])
    # NPC dialogue may address the player. Outside dialogue, the narrator may
    # describe visible surroundings but cannot invent the PC's position,
    # possessions, recent actions or inner thoughts.
    narration = re.sub(r'「[^」]*」', '', opening)
    subject = r'(?:你|主角|' + name + r')'
    if re.search(subject + r'(?:便|於是|緩緩地?|立刻|慢慢地?)?(?:推開|走進|走向|走到|走出|拿起|坐下|轉身|說道?|問道?|詢問|感到|心想|決定|接受|答應|站在|坐在|正|剛|已|手裡|手中|腦海|心裡)', narration):
        raise RuleError('開場替主角選擇了動作、台詞或感受，需要重新呈現。')


def preferences(raw):
    if not isinstance(raw, dict):
        raise RuleError('請先描述你想玩的故事。')
    result = {}
    for key in ('genre', 'difficulty', 'player_name', 'player_background', 'wishes'):
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value) > 3000:
            raise RuleError('故事偏好過長或格式不正確。')
        result[key] = value.strip()
    if not result['wishes'] and not result['genre']:
        raise RuleError('請選擇題材，或寫下你想玩的故事。')
    if type(raw.get('permadeath', False)) is not bool:
        raise RuleError('請選擇死亡規則。')
    result['permadeath'] = raw.get('permadeath', False)
    result.update(defaults(result['genre'], result['wishes']))
    level=difficulty(result['difficulty'] or '一般')
    if level['key'] not in DIFFICULTIES:
        raise RuleError('請選擇故事體驗、一般或困難。')
    result['difficulty']=level['key']
    result['difficulty_guidance']=level['description']
    return result


def normalize_plan(raw):
    """Normalize equivalent labels only; never fill missing fictional facts."""
    plan = copy.deepcopy(raw)
    if isinstance(plan, dict) and isinstance(plan.get('player'), dict):
        player = plan['player']
        if 'goal' not in player and 'wishes' in player:
            player['goal'] = player.pop('wishes')
    return plan


def build_world(plan, prefs):
    """Validate a small blueprint and construct the full authoritative seed."""
    prefs = preferences(prefs)
    plan = normalize_plan(plan)
    if not isinstance(plan, dict) or set(plan) != {'title', 'background', 'rules', 'player', 'location', 'npc', 'opening'}:
        raise RuleError('世界草案資料不完整，請重新生成。')
    for key in ('title', 'background', 'opening'):
        _text(plan[key], key, 6000 if key != 'title' else 120)
    if not isinstance(plan['rules'], list) or not 1 <= len(plan['rules']) <= 8:
        raise RuleError('世界草案需要明確的世界規則。')
    for rule in plan['rules']:
        _text(rule, '世界規則', 1000)
    player, npc, location = plan['player'], plan['npc'], plan['location']
    pkeys = {'name', 'species', 'role', 'background', 'goal', 'skills', 'powers', 'items'}
    nkeys = {'name', 'species', 'role', 'description', 'personality', 'values', 'concern', 'boundary', 'levers',
             'condition', 'priorities', 'appraisal', 'attraction', 'stance'}
    if not isinstance(player, dict) or set(player) != pkeys or not isinstance(npc, dict) or set(npc) != nkeys:
        raise RuleError('角色草案缺少身分、能力或 NPC 個人基礎。')
    if not isinstance(location, dict) or set(location) - {'name', 'description', 'nearby','objects'} or not {'name', 'description'} <= set(location):
        raise RuleError('需要完整的起點資料。')
    for key in pkeys - {'skills', 'powers', 'items'}:
        _text(player[key], '主角' + key)
    for key in nkeys:
        _text(npc[key], '人物' + key)
    for key in ('name', 'description'):
        _text(location[key], '起點' + key)
    nearby = location.get('nearby', [])
    if not isinstance(nearby, list) or len(nearby) > 2:
        raise RuleError('附近地點最多兩個。')
    for place in nearby:
        if not isinstance(place, dict) or set(place) != {'name', 'description'}:
            raise RuleError('附近地點需要名稱及景物描述。')
        for value in place.values():
            _text(value, '附近地點')
    objects=location.get('objects',[])
    if not isinstance(objects,list) or len(objects)>20:
        raise RuleError('同場可互動物件最多二十件。')
    names=set()
    for item in objects:
        if (not isinstance(item,dict) or set(item)!={'name','type','source_quote','force_profile'}
                or item['type'] not in ('door','crate','object')):
            raise RuleError('場景物件格式不完整。')
        name=_text(item['name'],'物件名稱',80)
        quote=_text(item['source_quote'],'物件來源',240)
        if name in names or chinese(name) not in quote or quote not in location['description']:
            raise RuleError('場景物件未有唯一名稱或已建立描述。')
        names.add(name)
        profile=item['force_profile']
        if profile is not None and (not isinstance(profile,dict) or
                set(profile)!={'tier','effect_key','initial','source_quote','initial_source_quote'}):
            raise RuleError('場景物件強度格式無效。')
    if not isinstance(player['skills'], list) or not 1 <= len(player['skills']) <= 8:
        raise RuleError('主角需要一至八項普通能力。')
    for skill in player['skills']:
        _text(skill, '技能', 200)
    if not isinstance(player['powers'], list) or len(player['powers']) > 2:
        raise RuleError('起始超自然能力最多兩項，沒有時應留空。')
    if not isinstance(player['items'], list) or len(player['items']) > 4:
        raise RuleError('起始物品最多四項。')
    for power in player['powers']:
        if not isinstance(power, dict) or set(power) != {'name', 'effect', 'limits'}:
            raise RuleError('每項能力需要名稱、效果與限制。')
        for value in power.values():
            _text(value, '能力', 1200)
    for item in player['items']:
        if not isinstance(item, dict) or set(item) != {'name', 'description'}:
            raise RuleError('每件物品需要名稱及用途。')
        for value in item.values():
            _text(value, '物品', 1000)
    validate_opening(plan)
    if prefs['magic'] == '沒有超自然能力' and player['powers']:
        raise RuleError('草案加入了你未選擇的超自然能力，請重新生成。')
    state = initial_state()
    state['campaign_id'] = 'world-' + uuid.uuid4().hex
    source = '新世界草案；使用者確認後於開場前建立'
    state['contract'].update(title=plan['title'], genre=prefs['genre'] or '自訂世界',
        difficulty=prefs['difficulty'] or '一般', difficulty_guidance=prefs['difficulty_guidance'], permadeath=prefs['permadeath'],
        canon_policy='身分、能力與超自然原因先建立，後裁定；不以結果倒造原因')
    state['pc'].update(name=player['name'], location='start', capabilities=copy.deepcopy(player['skills']),
        background=player['background'], role=player['role'], species=player['species'], goal=player['goal'],
        inventory={f'item_{i+1}': 1 for i in range(len(player['items']))})
    state['locations'] = {'start': {'name': location['name'], 'description': location['description'],
                                   'crowd': '附近還有幾位居民，各自忙著手上的事，尚未逐一認識。', 'exits': {}}}
    for index, place in enumerate(nearby):
        key = f'near_{index+1}'
        state['locations'][key] = {**copy.deepcopy(place), 'exits': {'start': {'known': True, 'clear': True}}}
        state['locations']['start']['exits'][key] = {'known': True, 'clear': True}
    from .npc_visibility import appearance_label
    state['npcs'] = {'guide': {'id': 'guide', 'name': npc['name'],
        'public_name': appearance_label(npc['description'].replace(npc['name'], '').replace(chinese(npc['name']), '')),
        'name_known': False, 'location': 'start', 'known': True,
        'alive': True, 'description': npc['description'],
        'anchor': {k: npc[k] for k in ('values', 'concern', 'boundary', 'levers')},
        'encounter': {k: npc[k] for k in ('condition', 'priorities', 'appraisal', 'attraction', 'stance')},
        'knowledge': ['自己的身分與當前活動'], 'conditions': [],
        'inner_life': {'personality': {'description': npc['personality'], 'basis': source, 'established_revision': 0},
                       'limits': [], 'current_emotions': [], 'relationships': {}, 'memories': [], 'personality_history': []}}}
    state['canon'] = {'version': 1, 'actors': {}, 'powers': {}, 'flags': {}, 'uses': []}
    for actor_id, person in ((state['pc']['id'], player), ('guide', npc)):
        establish(state, {'kind': 'identity', 'actor': actor_id, 'species': person['species'], 'role': person['role'],
            'forms': {'base': person['species'] + '的已建立外形；沒有其他已建立形態'}, 'current_form': 'base'}, source, 0, RuleError)
    for index, power in enumerate(player['powers']):
        establish(state, {'kind': 'power', 'id': f'power_{index+1}', 'actor': state['pc']['id'],
            'name': power['name'], 'effect': power['effect'] + '；限制：' + power['limits'],
            'requires_flags': [], 'result_form': None}, source, 0, RuleError)
    state['world'] = {'background': plan['background'], 'rules': copy.deepcopy(plan['rules']),
                      'preferences': prefs, 'source': source}
    if objects:
        state['world']['entities']={}
        for index,item in enumerate(objects):
            key=f'scene_object_{index+1}'
            state['world']['entities'][key]={
                'name':item['name'],'type':item['type'],'location':'start',
                'description':item['source_quote'],'values':{},'value_sources':{}}
            if item['force_profile'] is not None:
                from .calibrated_difficulty_trial import register_force_profile
                profile=item['force_profile']
                state=register_force_profile(state,key,profile['tier'],
                    profile['effect_key'],profile['initial'],profile['source_quote'],
                    profile['initial_source_quote'])
    state['item_catalog'] = {f'item_{i+1}': {**copy.deepcopy(item), 'source': source}
                             for i, item in enumerate(player['items'])}
    state['media'] = {'scenes': {}, 'portraits': {}, 'items': {}}
    state['facts'] = []
    return state


def generate_plan(raw, model_url, scene_trial=False, prior_worlds=None):
    prefs = preferences(raw)
    frame, setting = _creative_direction(prior_worlds)
    schema=copy.deepcopy(WORLD_SCHEMA)
    def bound(node):
        if node.get('type')=='string':node.update(minLength=1,maxLength=120)
        for child in node.get('properties',{}).values():bound(child)
        if isinstance(node.get('items'),dict):bound(node['items'])
    bound(schema)
    schema['properties']['title']['maxLength']=60
    schema['properties']['background']['maxLength']=240
    schema['properties']['opening']['maxLength']=400
    schema['properties']['location']['properties']['nearby']['maxItems']=1
    instruction=WORLD_SYSTEM+'\n這是快速開局。世界背景與開場各約八十字，開場必須在完整句子的句號、問號或驚嘆號結束；其他欄位各用一個短句（約十五至三十字），只建立起點與最多一個附近地點。普通人物不必有秘密或任務。不預寫後續場景、對白與遠處人物。保留玩家明確要求；細節可在實際接觸時再建立。\n下方「開局方向」與「生活環境」是今次新世界的具體起點，須依玩家題材調整，但不可改為另一種環境。若玩家明確指定起點，以玩家要求為準。即使題材黑暗，第一幕仍應有正常生活；不要把灰霧、礦坑、工業廢墟、拾荒者或年長引路人當作隨機世界的預設。第一幕不必有世界危機或神秘物件，留到玩家探索後才逐步建立。只改人名或建築名稱不算新故事。'
    requested=prefs['player_name']
    if requested:
        pair=PAIR.fullmatch(requested)
        if pair:schema['properties']['player']['properties']['name']={'type':'string','enum':[requested]}
        else:
            literal=re.escape(requested).replace(r'\-','-')
            pattern=('^'+NAME_PREFIX+r'{1,40}（'+literal+r'）$' if re.fullmatch(r"[A-Za-z][A-Za-z '\-]*",requested)
                     else '^'+literal+r"（[A-Za-z][A-Za-z '-]{0,80}）$")
            schema['properties']['player']['properties']['name']={'type':'string','pattern':pattern}
    for attempt in range(2):
        with stage('建立世界與人物' if attempt == 0 else '重新構思不同開場'):
          try:
            plan = normalize_plan(_complete([{'role': 'system', 'content': '已核對的 RPG OS v1.01 原規則摘錄：\n' + excerpts('observe')+'\n\n'+instruction},
                          {'role': 'user', 'content': json.dumps({
                              '玩家偏好': {**prefs, 'wishes': '' if prefs['wishes'].casefold() == 'random' else prefs['wishes'],
                                       'player_background': '' if prefs['player_background'].casefold() == 'random' else prefs['player_background']},
                              '開局方向': frame[1], '生活環境': setting[1]}, ensure_ascii=False)}], model_url, 2400, 0.65, timeout=600,response_schema=schema))
          except InvalidJSONError as exc:
            raise RuleError('新世界草案未能完整產生，尚未建立或切換世界。你的設定與目前故事仍保留，請稍後再試。') from exc
        if not isinstance(plan,dict) or not all(isinstance(plan.get(key),dict) for key in ('player','npc','location')) or not all(isinstance(plan[key].get('name'),str) for key in ('player','npc','location')):
            raise RuleError('世界草案資料不完整，尚未建立或切換世界，請重新生成。')
        if prefs['wishes'].casefold() not in ('', 'random') or not _similar_to_prior(plan,prior_worlds):
            break
        if attempt:
            raise RuleError('新草案與已有世界太相似，尚未建立或切換故事，請重新生成。')
        frame, setting = _creative_direction([{'entry_frame':frame[0], 'entry_setting':setting[0]}, *(prior_worlds or [])])
    # A local 8B model can ignore language/authorship instructions even while
    # producing valid JSON. Repair only opening prose, never grant new facts.
    if isinstance(plan, dict) and isinstance(plan.get('player'), dict) and isinstance(plan.get('opening'), str):
        try:
            validate_opening(plan, hide_npc_name=True)
        except (RuleError, KeyError, TypeError):
            try:
                with stage('整理開場'):
                  replacement = _complete([
                    {'role': 'system', 'content': '只回傳 JSON：{"opening":"兩段自然繁體中文開場"}。請重新寫完整兩段，每段一至兩句，最後一句必須以句號、問號或驚嘆號完成。只描寫給定景物與 NPC 日常活動和一句直接台詞。不可寫主角的動作、台詞、感受、承諾或決定。不可新增人物、能力、物品或事件。不要使用英文句子。避免以「你」作主詞，用景物或 NPC 作主詞。'},
                    {'role': 'user', 'content': json.dumps({'location': plan.get('location'), 'npc': plan.get('npc')}, ensure_ascii=False)}
                ], model_url, 500, 0.3,response_schema=obj({'opening':text()}))
                if not isinstance(replacement, dict) or set(replacement) != {'opening'}:
                    raise RuleError('開場重寫未完成。')
                plan['opening'] = replacement['opening']
                validate_opening(plan, hide_npc_name=True)
            except (RuleError, KeyError, TypeError):
                # These two AI-authored descriptions were established before
                # play; reuse them rather than invent a PC action or new cause.
                plan['opening'] = str(plan.get('location', {}).get('description', '')) + '\n\n' + str(plan.get('npc', {}).get('description', ''))
                validate_opening(plan, hide_npc_name=True)
    # Explicit name preference is an authoring constraint, not optional model prose.
    if prefs['player_name']:
        requested=prefs['player_name'];pair=PAIR.fullmatch(plan['player']['name'].strip())
        actual=pair[2] if pair and re.fullmatch(r"[A-Za-z][A-Za-z '\-]*",requested) else chinese(plan['player']['name'])
        if actual.casefold()!=chinese(requested).casefold():
            raise RuleError('草案沒有沿用你指定的角色姓名，請重新生成。')
    holders={'player':plan['player'],'npc':plan['npc'],'location':plan['location'],
             **{'near_'+str(i):p for i,p in enumerate(plan['location'].get('nearby',[]))}}
    missing={key:item['name'] for key,item in holders.items() if not has_english(item['name'])}
    if missing:
        with stage('補齊英文名稱'):
            translated=_complete([{'role':'system','content':'只翻譯或音譯下列人物／地點名稱為簡短英文名稱，不新增背景。只回傳相同鍵的 JSON 物件，值只用英文字母、空格、連字號及撇號。'},
                {'role':'user','content':json.dumps(missing,ensure_ascii=False)}],model_url,350,.2,response_schema=obj({key:text() for key in missing}))
        if not isinstance(translated,dict) or set(translated)!=set(missing):
            raise RuleError('英文名稱整理未完成，目前冒險沒有改動。')
        for key,value in translated.items():
            if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z][A-Za-z '\-]{0,80}",value):
                raise RuleError('英文名稱格式不正確，目前冒險沒有改動。')
            holders[key]['name']=missing[key]+'（'+value+'）'
    scene_setup=None
    if scene_trial:
        from .scene_setup_trial import extract_scene_objects
        try:
            rows,rejected,tokens=extract_scene_objects(plan['location']['description'],model_url)
            scene_setup={'status':'completed','accepted':len(rows),
                         'rejected':len(rejected),'input_tokens':tokens}
        except (RuleError,ValueError,TypeError) as exc:
            rows=[];scene_setup={'status':'failed','error':str(exc)}
        plan['location']['objects']=rows
    state = build_world(plan, prefs)
    state['world']['entry_frame'] = frame[0]
    state['world']['entry_setting'] = setting[0]
    result={'plan':plan,'preferences':prefs,'seed':state}
    if scene_setup is not None:result['scene_setup']=scene_setup
    return result


def generate_world(raw, model_url, scene_trial=False, prior_worlds=None):
    """Create a playable opening without a future story blueprint."""
    candidate=generate_plan(raw,model_url,scene_trial=scene_trial,prior_worlds=prior_worlds)
    return candidate
