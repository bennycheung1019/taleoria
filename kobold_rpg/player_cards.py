"""Validate legacy player card data when importing an older save."""

def validate(value, revision, error):
    if not isinstance(value,dict):raise error('存檔人物公開資料格式不正確。')
    facts=value.get('facts',{})
    if not isinstance(facts,dict):raise error('存檔人物已知資訊格式不正確。')
    entries=[(item,True) for item in facts.values()]
    entries.extend((value[field],False) for field in ('relationship','condition') if field in value)
    for item,fact in entries:
        if (not isinstance(item,dict) or not isinstance(item.get('text'),str)
                or not isinstance(item.get('evidence'),str)
                or type(item.get('revision')) is not int or not 0<=item['revision']<=revision
                or (fact and item.get('kind') not in ('said','observed'))):
            raise error('存檔人物公開資料缺少內容或來源。')
