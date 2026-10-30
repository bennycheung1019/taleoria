"""Creation defaults and qualitative stakes, not hidden success multipliers."""
import re

STORY_TYPES = {
    '黑暗奇幻': {'tone': '有壓力與人情味的探索，危險有原因', 'magic': '少量，能力必須有明確來源'},
    '江湖武俠': {'tone': '江湖探索、人情、恩怨與俠義', 'magic': '武學依來源與訓練成立，不默認法術或神通'},
    '星際探索': {'tone': '探索未知、科技難題與不同立場', 'magic': '科技有明確功能與限制，不默認超自然異能'},
    '懸疑調查': {'tone': '線索、證據與人物動機，真相不為轉折倒改', 'magic': '沒有超自然能力'},
    '日常小鎮': {'tone': '溫暖細膩的日常與人際互動', 'magic': '沒有超自然能力'},
    '自訂世界': {'tone': '依自由描述決定，預設開放探索', 'magic': '依自由描述先行建立，未指定時主角沒有超自然能力'},
}
DIFFICULTIES = {
    '以故事體驗為主': {'label': '故事體驗', 'description': '線索與風險提醒較明確，起始準備較寬裕，較少立即致命的處境。失敗仍有合理後果。'},
    '一般': {'label': '一般', 'description': '依背景安排線索、資源與危險。觀察、準備及人物選擇都會影響結果。'},
    '困難': {'label': '困難', 'description': '起始資源較緊、對手準備較充分，線索需要主動調查。危險仍有依據，不會憑空強化敵人或安排必死。'},
}


def defaults(genre, wishes=''):
    result = dict(STORY_TYPES.get(genre, STORY_TYPES['自訂世界']))
    if re.search(r'(沒有|不要|不使用|不用|無).{0,6}(魔法|異能|超自然)', wishes):
        result['magic'] = '沒有超自然能力'
    elif re.search(r'(想|要|擁有|加入|設定|會|有).{0,16}(魔法|異能|超自然)', wishes):
        result['magic'] = '依玩家自由描述先建立超自然能力的來源、效果及限制'
    return result


def difficulty(value):
    key = {'Hard': '困難', 'Normal': '一般', '故事體驗': '以故事體驗為主'}.get(value, value)
    return {**DIFFICULTIES.get(key, DIFFICULTIES['一般']), 'key': key}
