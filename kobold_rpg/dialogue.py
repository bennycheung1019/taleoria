"""Provenance-bound dialogue context; no inferred trust, consent or world facts."""
import re
import unicodedata
from difflib import SequenceMatcher

HISTORY_LIMIT = 4
QUOTES = re.compile(r'(「[^」]*」|『[^』]*』|“[^”]*”|"[^"]*")', re.S)


def quoted_texts(text):return [quote[1:-1] for quote in QUOTES.findall(text)]


def spoken_text(text):
    clean=text.replace('\\"','"').replace("\\'","'")
    quoted=list(QUOTES.finditer(clean))
    outside=QUOTES.sub('',clean).strip(' ，,。.!！?？:：')
    if quoted and (not outside or re.fullmatch(r'(?:I\s+)?(?:said|say|ask|asked)|(?:我)?(?:說|問)(?:道)?',outside,re.I)):
        return '\n'.join(match.group(1)[1:-1].strip() for match in quoted)
    return clean.strip()


def player_utterance(action):
    understanding=action.get('understanding')
    if understanding is None:return spoken_text(action['text'])
    # Semantic parsing may list spans out of order. Restore original order;
    # unspoken thoughts and performed actions never become NPC-heard dialogue.
    speech=sorted(understanding['speech'],key=action['text'].find)
    return '\n'.join(spoken_text(part) for part in speech)


def recent_turns(recent):
    result=[]
    for row in recent or []:
        if isinstance(row,str):result.append({'narration':row})
        elif isinstance(row,dict) and isinstance(row.get('narration'),str):
            result.append({key:row[key] for key in ('declaration','narration','target','kind','revision','has_events','witnesses') if key in row})
    return result[-HISTORY_LIMIT:]


def split_stance(text):
    """Move only explicit requests for an answer out of physical/social stance.

    Waiting for help, guarding a door, refusing contact, etc. remain untouched.
    Extracted requests remain historical data; they are not deemed answered.
    """
    stable=[];requests=[]
    for clause in re.split(r'[，,；;。]\s*',text):
        if not clause.strip():continue
        waiting=re.match(r'^(?:正在)?(?:等待|等候)(?:對方|玩家|你|您|他|她)(?:先|進一步|繼續)?(?:說明|回答|答覆|回應|解釋|交代)',clause)
        english=re.match(r'^(?:waiting|awaiting)\s+(?:for\s+)?(?:the\s+)?(?:player|you|them|him|her)\s+to\s+(?:answer|explain|describe|reply)\b',clause,re.I)
        (requests if waiting or english else stable).append(clause.strip())
    return '，'.join(stable),requests


def reference_words(utterance, past):
    """Retrieve literal prior words named by the player, never infer an answer."""
    if not past:return None
    chinese=re.findall(r'[\u4e00-\u9fff]{2,}',utterance)
    pairs={part[i:i+2] for part in chinese for i in range(len(part)-1)}
    stop={'why','what','when','where','which','would','could','should','have','that','this','your','said','says','please','explain'}
    words=set(re.findall(r'\b[a-z]{4,}\b',utterance.lower()))-stop
    quotes=[(quote,row.get('revision')) for row in reversed(past) for quote in quoted_texts(row['narration'])]
    score=lambda quote:sum(pair in quote for pair in pairs)+2*sum(word in quote.lower() for word in words)
    if not quotes:return None
    quote,revision=max(quotes,key=lambda pair:score(pair[0]))
    if score(quote)<2:return None
    return {'quote':quote,'source_revision':revision,
            'scope':'先前回應中的原話，只是說過，不證明其內容是真相。'}


def dialogue_context(npc, action, recent):
    past=[row for row in recent_turns(recent)
          if row.get('target',action['target']) in ('',action['target'])
          and ('witnesses' not in row or action['target'] in row['witnesses'])]
    recorded=npc.get('dialogue',{})
    if recorded and not any(row.get('revision')==recorded['revision'] for row in past):
        past=recent_turns([{'revision':recorded['revision'],'target':action['target'],
            'declaration':recorded['player_said'],'narration':recorded['response_as_narrated']},*past])
        past.sort(key=lambda row:row.get('revision',-1))
    stance,requests=split_stance(npc['encounter']['stance'])
    previous_requests=list(dict.fromkeys([*recorded.get('previous_requests',[]),*requests]))[-4:]
    turn={'player_says':player_utterance(action),'addressed_to':action['target']}
    if re.search(r'\bwhy\b|為什麼|為甚麼|為何',turn['player_says'],re.I):
        turn['response_task']='回應這次原因追問：根據自己知道的資訊解釋、不知道就坦承，或依個性具體拒答。若是在追問你先前的說法，說明當時判斷的依據或承認只是猜測。不能用舊問題代替解釋。'
    reference=reference_words(turn['player_says'],past)
    if reference:turn['referring_to_previous_words']=reference
    return {
        'current_stance':stance,
        'past_conversation':past,
        'conversation_state':{
            'previous_requests':previous_requests,
            'scope':'先前提出的要求，不代表已被回答或持續主導話題；不是新的玩家宣告。',
            'last_exchange_revision':recorded.get('revision'),
        },
        'current_turn':turn,
    }


def record_exchange(state, action, proposal, revision, previous=None):
    """Called only inside approval's transaction; retain literal, accepted data."""
    if action['kind']!='speak' or not action.get('target') or proposal['outcome']=='clarify':return
    npc=state['npcs'].get(action['target'])
    if not npc or not player_utterance(action):return
    stable,requests=split_stance(npc['encounter']['stance'])
    prior=npc.get('dialogue',{}).get('previous_requests',[])
    if previous:prior=[*prior,*split_stance(previous['encounter']['stance'])[1]]
    npc['dialogue']={'revision':revision,'player_said':player_utterance(action),
        'response_as_narrated':proposal['narration'],
        'previous_requests':list(dict.fromkeys([*prior,*requests]))[-4:]}
    # No remaining stance is explicitly recorded as unknown, not friendliness.
    if requests:npc['encounter']['stance']=stable or '未另記錄當前參與態度'


def validate_record(record, revision, error):
    keys={'revision','player_said','response_as_narrated','previous_requests'}
    if not isinstance(record,dict) or set(record)!=keys or type(record['revision']) is not int or not 0<record['revision']<=revision:
        raise error('存檔對話紀錄缺少有效來源版本。')
    if any(not isinstance(record[key],str) or not record[key].strip() or len(record[key])>8000 for key in ('player_said','response_as_narrated')):
        raise error('存檔對話原文格式不正確。')
    if not isinstance(record['previous_requests'],list) or len(record['previous_requests'])>4 or any(not isinstance(text,str) or not text.strip() or len(text)>1000 for text in record['previous_requests']):
        raise error('存檔先前提問紀錄格式不正確。')


def speech_sentences(text):
    return [fingerprint(sentence) for quote in quoted_texts(text)
            for sentence in re.split(r'[。！？!?；;\n]+',quote) if len(fingerprint(sentence))>=12]


def fingerprint(text):
    text=unicodedata.normalize('NFKC',text).translate(str.maketrans('着问说','著問說'))
    text=re.sub(r'[（(][A-Za-z][^）)]*[）)]','',text)
    return ''.join(character.lower() for character in text if character.isalnum())


def near_same(a,b):
    # A changed negation or quantity can be a changed decision, not repetition.
    polarity=lambda value:re.findall(r'不|沒|未|無|別|not|never|no|\d+',value)
    return polarity(a)==polarity(b) and SequenceMatcher(None,a,b).ratio()>=.9


def history_message(row, earlier):
    """Repair the prompt's examples, not the journal or any accepted world fact.

    Only known repetition with no recorded events gets a literal factual recap.
    The original remains in the journal and in repeat validation's raw history.
    """
    if row.get('has_events') is not False:return row['narration']
    if repetition_issue({'kind':'speak','target':row.get('target') or 'npc','text':row.get('declaration','')},
            {'narration':row['narration']},earlier):
        return '歷史紀錄摘要：這一輪的回應重複了先前已出現的長台詞，沒有寫入新的狀態事件。原文仍保存在完整記事。這是對既有紀錄的說明，不是 NPC 新說的一句話。'
    return row['narration']


def repetition_issue(action,proposal,recent):
    """Quality advice for history preparation, never a delivery/approval gate."""
    if action['kind']!='speak' or not action.get('target'):return
    value=fingerprint(proposal['narration'])
    if len(value)<18:return
    sentences=speech_sentences(proposal['narration'])
    if len(sentences)!=len(set(sentences)):
        return '同一則回應重複了較長的台詞。'
    # Explicit requests to repeat may elicit the same answer. Short refusals
    # stay permitted, without treating any repeated request as a reroll.
    past=recent_turns(recent)
    if re.search(r'再說|再講|重複|repeat|say\b.*\bagain|what did you say',player_utterance(action),re.I):return
    if any(value==fingerprint(row['narration']) for row in past):
        return '這段回應整段重複先前內容。'
    old=[sentence for row in past for sentence in speech_sentences(row['narration'])]
    old_quotes=[fingerprint(quote) for row in past for quote in quoted_texts(row['narration'])]
    for quote in quoted_texts(proposal['narration']):
        clean=fingerprint(quote)
        if len(clean)>=40 and any(near_same(clean,prior) for prior in old_quotes):
            return '回應沿用了先前較長的台詞。'
    repeated=sum(len(sentence) for sentence in sentences if any(near_same(sentence,prior) for prior in old))
    if repeated>=35 and repeated>=.75*sum(map(len,sentences)):
        return '回應的大部分長台詞沿用舊對話。'
