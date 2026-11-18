"""验证来源、单期偏离、区域规则和重复接收的既有调用链。"""
import json,unittest
from pathlib import Path
from climate_analysis.evidence import connect,receive
from climate_analysis.metrics import compare
from climate_analysis.context import decide
from climate_analysis.report import generate,difference
DATA=json.loads((Path(__file__).resolve().parents[1]/'data/example.json').read_text(encoding='utf8'))
class Chain(unittest.TestCase):
 def setUp(self):self.db=connect(':memory:')
 def tearDown(self):self.db.close()
 def test_measurement_chain(self):
  for doc in DATA['documents']:receive(self.db,doc)
  a,b=[compare(self.db,t) for t in DATA['known_at']]
  self.assertEqual([row['delta'] for row in (a[0],b[0])],[1,20])
  self.assertEqual(decide(self.db,DATA['known_at'][0],a[0])['status'],'常态')
  after=decide(self.db,DATA['known_at'][1],b[0]);self.assertEqual(after['status'],'关注')
  self.assertEqual(after['action'],'避险');self.assertEqual(len(after['sources']),3)
 def test_report_compares_decisions(self):
  for doc in DATA['documents']:receive(self.db,doc)
  a,b=[generate(self.db,t) for t in DATA['known_at']]
  # 旧样本没有潮位、雨量、排水工况和街区阈值，新分析不产生任何避险判断
  self.assertEqual([report['decisions'] for report in (a,b)],[[],[]])
  self.assertEqual(difference(a,b)['changed'],[])
 def test_repeat_and_conflict(self):
  doc=DATA['documents'][0];self.assertEqual(receive(self.db,doc),receive(self.db,doc))
  changed=json.loads(json.dumps(doc));changed['records'][0]['payload']['value']+=1
  with self.assertRaises(ValueError):receive(self.db,changed)
