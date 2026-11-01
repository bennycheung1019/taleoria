import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kobold_rpg.action_transaction_trial import run_pending_turn
from kobold_rpg.engine import Engine,RuleError
from test_action_registry_trial import intent,lock_rule,step,world


class PendingActionTests(unittest.TestCase):
    @patch('kobold_rpg.action_workflow_trial.count',return_value=None)
    @patch('kobold_rpg.action_workflow_trial.budget',return_value=None)
    def test_failed_audit_reuses_frozen_dice_then_commits_once(self,*_):
        with tempfile.TemporaryDirectory() as folder:
            engine=Engine(Path(folder)/'copy.sqlite3',seed=world())
            proposed=intent([step('custom','side_door',item_id='lockpick',
                rule_id='pick_lock',difficulty={'base':10,'factors':[],'target':10})],lock_rule(engine.state()))
            calls=[];audits=0
            def complete(messages,*_args,**_kwargs):
                nonlocal audits
                content=messages[0]['content'];calls.append(content)
                if '你只把最後一則' in content:return json.dumps(proposed,ensure_ascii=False)
                if '依 host_result' in content:
                    payload=json.loads(content.split('\n',1)[1])
                    return json.dumps({'decision_id':payload['decision_id'],
                        'narration':'鎖舌已彈開，門仍關著。'},ensure_ascii=False)
                if '獨立核對候選敘事' in content:
                    audits+=1
                    return json.dumps({'consistent':audits>1,
                        'conflicts':['請再核對'] if audits==1 else [],
                        'added_pc_actions':[],'unsupported_facts':[]},ensure_ascii=False)
                self.fail('unexpected model call')
            action='我試用工具撬鎖'
            with self.assertRaises(RuleError):
                run_pending_turn(engine,'same-id',0,action,'http://none',complete)
            with engine.connect() as db:
                row=db.execute('SELECT seed,intent,decision FROM action_trial_pending').fetchone()
                frozen=json.loads(row['decision'])
                self.assertEqual(db.execute('SELECT count(*) FROM journal').fetchone()[0],0)
            self.assertEqual(engine.state()['revision'],0)
            first=run_pending_turn(engine,'same-id',0,action,'http://none',complete)
            second=run_pending_turn(engine,'same-id',0,action,'http://none',complete)
            self.assertEqual(first['decision'],frozen)
            self.assertEqual(second['decision'],frozen)
            self.assertEqual(first['revision'],1)
            self.assertEqual(engine.state()['revision'],1)
            self.assertEqual(sum('你只把最後一則' in call for call in calls),1)
            with engine.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM journal').fetchone()[0],1)
            with self.assertRaises(RuleError):
                run_pending_turn(engine,'same-id',0,'另一個行動','http://none',complete)


if __name__=='__main__':unittest.main()
