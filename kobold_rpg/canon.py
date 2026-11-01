"""Register established identities and abilities during world creation."""
import copy


def text(value, label, error):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise error(label + "需要具體文字")


def actor(state, actor_id, error):
    if actor_id == state['pc']['id']:
        return state['pc']
    if not isinstance(actor_id, str) or actor_id not in state['npcs']:
        raise error('人物尚未建立，不能引用其身分或能力')
    return state['npcs'][actor_id]


def establish(state, data, source, revision, error):
    """Only called by the explicit GM operation, never by model events."""
    if 'canon' not in state:
        raise error('此戰役尚未啟用身分與能力登記；不要自動改寫舊戰役')
    if not isinstance(data, dict):
        raise error('世界建立資料必須是物件')
    canon = state['canon']
    kind = data.get('kind')
    if kind == 'identity':
        if set(data) != {'kind', 'actor', 'species', 'role', 'forms', 'current_form'}:
            raise error('身分需要 kind、actor、species、role、forms、current_form')
        actor(state, data['actor'], error)
        if data['actor'] in canon['actors']:
            raise error('已建立的身分不能覆寫；真正錯誤可明確回溯，變身須有先行能力')
        for field in ('species', 'role', 'current_form'):
            text(data[field], field, error)
        if not isinstance(data['forms'], dict) or data['current_form'] not in data['forms'] or len(data['forms']) > 12:
            raise error('形態清單必須包含目前形態')
        for key, value in data['forms'].items():
            text(key, '形態 ID', error); text(value, '形態描述', error)
        canon['actors'][data['actor']] = {k: copy.deepcopy(data[k]) for k in ('species', 'role', 'forms', 'current_form')}
        canon['actors'][data['actor']].update(source=source, established_revision=revision, powers=[])
    elif kind == 'form':
        if set(data) != {'kind', 'actor', 'id', 'description'}:
            raise error('新形態需要 kind、actor、id、description')
        for field in ('actor', 'id', 'description'):
            text(data[field], field, error)
        record = canon['actors'].get(data['actor'])
        if not record or data['id'] in record['forms']:
            raise error('人物未建立或該形態已存在；不能覆寫')
        record['forms'][data['id']] = data['description']
        canon.setdefault('form_sources', {})[data['actor'] + ':' + data['id']] = {'source': source, 'established_revision': revision}
    elif kind == 'power':
        if set(data) != {'kind', 'id', 'actor', 'name', 'effect', 'requires_flags', 'result_form'}:
            raise error('能力需要 kind、id、actor、name、effect、requires_flags、result_form')
        for field in ('id', 'actor', 'name', 'effect'):
            text(data[field], field, error)
        if data['id'] in canon['powers'] or data['id'] in state['abilities']:
            raise error('能力已建立，不可覆寫來源與效果')
        record = canon['actors'].get(data['actor'])
        if not record:
            raise error('先建立能力擁有人的身分')
        flags = data['requires_flags']
        if not isinstance(flags, list) or len(flags) > 12 or any(not isinstance(f, str) or f not in canon['flags'] for f in flags):
            raise error('能力條件只能引用先前已登記的旗標')
        if data['result_form'] is not None and data['result_form'] not in record['forms']:
            raise error('變身目的形態必須在人物身分建立時已登記')
        rule = {k: copy.deepcopy(v) for k, v in data.items() if k not in {'kind', 'id'}}
        rule.update(source=source, established_revision=revision)
        canon['powers'][data['id']] = rule
        record['powers'].append(data['id'])
        if data['actor'] == state['pc']['id']:
            state['pc']['spells'].append(data['id'])
            state['abilities'][data['id']] = {'name': data['name'], 'effect': data['effect'], 'source': source}
    elif kind == 'flag':
        if set(data) != {'kind', 'id', 'value'} or type(data['value']) is not bool:
            raise error('觸發條件需要 kind、id、value（布林值）')
        text(data['id'], '條件 ID', error)
        canon['flags'][data['id']] = {'value': data['value'], 'source': source, 'established_revision': revision}
    else:
        raise error('世界建立只接受 identity、form、power 或 flag')
