"""Display aliases only: IDs, fictional facts and historical records stay intact."""
import re

LEGACY={'班':'Ben','哈克':'Hark','安雅':'Anya','霧橋鎮北門':'Mistbridge North Gate',
        '城門旁的避雨棚':'Gate-side Rain Shelter','河街':'River Street','渡口':'Ferry Pier',
        '霧橋鎮':'Mistbridge','北門':'North Gate','避雨棚':'Rain Shelter'}
PAIR=re.compile(r'^(.+?)[（(]([A-Za-z][A-Za-z0-9 .’\x27\-]{0,100})[）)]$')


def chinese(value):
    match=PAIR.fullmatch(value.strip())
    return match[1] if match else value.strip()


def has_english(value):
    return bool(PAIR.fullmatch(value.strip())) or bool(re.fullmatch(r'[A-Za-z][A-Za-z .\x27\-]{0,100}',value.strip()))


def aliases(state):
    result=dict(LEGACY)
    for person in [state['pc'],*state['npcs'].values(),*state['locations'].values()]:
        match=PAIR.fullmatch(person['name'].strip())
        if match:result[match[1]]=match[2]
    return result


def display(value, registry):
    if isinstance(value,dict):return {key:display(item,registry) for key,item in value.items()}
    if isinstance(value,list):return [display(item,registry) for item in value]
    if not isinstance(value,str):return value
    options=[]
    for name in sorted(registry,key=len,reverse=True):
        # Avoid treating ordinary Chinese words such as 交班 as a person's name.
        guard=r'(?<![\u3400-\u9fff])' if len(name)==1 else ''
        options.append(guard+re.escape(name)+r'(?:[（(]'+re.escape(registry[name])+r'[）)])?')
    pattern=re.compile('|'.join(options))
    def replace(match):
        base=chinese(match[0]);return base+'（'+registry[base]+'）'
    return pattern.sub(replace,value)
