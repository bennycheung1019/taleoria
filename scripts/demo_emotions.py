"""An explicitly synthetic, separate campaign for reviewing emotional continuity."""
from pathlib import Path
from kobold_rpg.engine import Engine


def build_demo(database="data/emotions-demo.sqlite3"):
    path = Path(database)
    if path.exists():
        return Engine(path)  # Never reset an existing demonstration campaign.
    engine = Engine(path)
    mira = {"id": "mira", "name": "米拉（Mira）", "location": "gate", "known": True,
            "alive": True, "description": "一名成年女子帶著包好的雨披，在門燈旁等候同伴。",
            "anchor": {"values": "珍惜自己的修補手藝，喜歡被當作有能力的人平等對待",
                       "concern": "想把修好的雨披交給朋友，不想被催促安排自己的時間",
                       "boundary": "不願因別人示好就被要求承諾親近或同行",
                       "levers": "細心聆聽、尊重她的選擇、對手藝的真誠興趣"},
            "encounter": {"condition": "平靜，在等候同伴", "priorities": "交付雨披，等候朋友",
                          "appraisal": "注意到班，尚未了解他的為人",
                          "attraction": "目前沒有浪漫或身體吸引；可以覺得一段交談愉快",
                          "stance": "願意短暫交談，仍保有自己的行程"},
            "knowledge": ["自己正在等候同伴", "自己的修補手藝"], "conditions": []}
    def accept(text, narration, events):
        revision = engine.state()["revision"]
        action = {"kind": "speak", "target": "hark", "text": text}
        p = engine.propose(action, {"outcome": "partial", "reason": "非正史示範：人工建立的可審閱情緒連續性案例，不是模型真實遊玩結果。",
                                  "narration": narration, "events": events}, revision, "synthetic-demo")
        engine.approve(p["id"], f"demo-{revision}")
    accept("【非正史示範設定】在既有城門場景加入米拉，建立現在及未來適用的性格細節。",
           "【獨立情緒示範】這不是你原本故事的延續。下列共同經歷是人工設定的示範資料。米拉在城門旁等候朋友。",
           [{"type": "establish_npc", "npc": mira},
            {"type": "npc_personality", "npc": "hark",
             "description": "嘴上務實，容易因別人體諒辛勞而感到溫暖；在弟弟與工作牽掛下會猶豫，不是逢人答應，也不是沒有感情。",
             "basis": "示範情境中的前瞻性性格建立，不回寫原本戰役的過去原因。", "limits": []},
            {"type": "npc_personality", "npc": "mira",
             "description": "感受細膩，慢慢熟悉別人後才願意分享私人想法；尊重比誇張讚美更能打動她，也會因被逼迫而疏遠。",
             "basis": "僅用於這個獨立示範人物的新建立性格，不保證她會愛上任何人。", "limits": []}])
    accept("【示範經歷】我謝謝哈克在雨中守門，問他是否需要替交班者傳話；也問米拉包裹裡的修補手藝。",
           "哈克緊繃的肩膀稍微放鬆。「有人記得我們也會淋雨，倒是不常見。」他笑了一下，仍留在門邊。米拉抬起包裹，開始說明那是剛修好的雨披。",
           [{"type": "social_experience", "npc": "hark", "subject": "ben",
             "observed": "班道謝並詢問是否需要替交班者傳話，沒有堅持哈克離崗。",
             "interpretation": "自己的辛勞被看見，也感到對方願意體諒責任；實際幫忙尚未完成。",
             "emotions": ["受到體諒而溫暖", "仍擔心交班延誤"],
             "changes": {"trust": {"before": None, "after": "更願意聽班說話，仍待觀察是否可靠"}}, "recalls": []},
            {"type": "social_experience", "npc": "mira", "subject": "ben",
             "observed": "班問起米拉手中的修補作品，讓她自行介紹。",
             "interpretation": "覺得班願意把她當作熟悉手藝的人聆聽，而不只關注她的外表。",
             "emotions": ["因手藝受重視而高興", "對陌生人仍稍有保留"],
             "changes": {"respect": {"before": None, "after": "對班尊重她手藝的態度有初步好感"}}, "recalls": []}])
    mira_memory = engine.state()["npcs"]["mira"]["inner_life"]["memories"][0]["id"]
    accept("【示範經歷】米拉介紹完手藝後，我說願意繼續聽她講，但若她要去交付雨披，也不用為我改變安排。",
           "米拉把雨披抱得輕鬆了些。「你真的願意聽這些細節？」她帶著笑意問。她沒有答應改變行程，卻主動接著說起最難補的一處裂口。",
           [{"type": "social_experience", "npc": "mira", "subject": "ben",
             "observed": "班表達想聽她繼續分享，也明說她不必為他改變行程。",
             "interpretation": "想起先前受到尊重的交談，覺得這次仍有自己作選擇的空間。",
             "emotions": ["交談受到珍惜而開心", "願意再多認識班一些"],
             "changes": {"affection": {"before": None, "after": "開始享受與班相處，並未因此形成浪漫承諾"}},
             "recalls": [mira_memory]}])
    return engine


if __name__ == "__main__":
    engine = build_demo()
    print(f"獨立情緒示範已準備：世界版本 {engine.state()['revision']}，原故事不受影響。")
