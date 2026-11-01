"""Read-only condition view for a paired narration experiment.

Values and concise descriptions are supplied by established state. This module
does not infer missing facts or change any entity or save.
"""
import copy

from .engine import RuleError


def narration_condition_view(record,include_sentence):
    """Serialize only the selected target's bounded, explicit condition facts."""
    if not isinstance(record,dict) or set(record)!={
            'target_name','source_sentence','action_result','attributes','unknowns',
            'condition_sentence'}:
        raise RuleError('物件狀況資料不完整。')
    for key in ('target_name','source_sentence','action_result'):
        if not isinstance(record[key],str) or not record[key].strip():
            raise RuleError('物件狀況缺少已建立文字。')
    attributes=record['attributes']
    if not isinstance(attributes,dict) or not 1<=len(attributes)<=8:
        raise RuleError('物件狀況數值超過範圍。')
    for key,item in attributes.items():
        if (not isinstance(key,str) or not key or not isinstance(item,dict) or
                set(item)!={'value','meaning'} or not isinstance(item['meaning'],str) or
                not item['meaning'].strip() or len(item['meaning'])>100 or
                not isinstance(item['value'],(bool,int,float,str))):
            raise RuleError('物件狀況數值或定義無效。')
        if key=='integrity' and (type(item['value']) is not int or
                                 not 0<=item['value']<=100):
            raise RuleError('完整度必須是 0 至 100 的整數。')
    unknowns=record['unknowns']
    if (not isinstance(unknowns,list) or len(unknowns)>8 or
            any(not isinstance(value,str) or not value.strip() or len(value)>80
                for value in unknowns)):
        raise RuleError('未知狀況格式無效。')
    sentence=record['condition_sentence']
    if not isinstance(sentence,str) or not sentence.strip() or len(sentence)>120:
        raise RuleError('簡短狀況句格式無效。')
    view={key:copy.deepcopy(record[key]) for key in
          ('target_name','source_sentence','action_result','attributes','unknowns')}
    if include_sentence:
        view['condition_sentence']=sentence
    return view
