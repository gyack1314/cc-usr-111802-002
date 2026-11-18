"""验证按适用时间配对、缺口说明与版本复议。"""
import json, unittest
from pathlib import Path
from climate_analysis.analysis import assess
from climate_analysis.evidence import connect, receive
from climate_analysis.report import generate, difference

SCENARIO=json.loads((Path(__file__).resolve().parents[1]/'data/drainage-scenario.json').read_text(encoding='utf8'))

def load(data):
    db=connect(':memory:')
    for doc in data['documents']:receive(db,doc)
    return db

def at(db,known_at):return {group['region'] or '未归属':group for group in assess(db,known_at)}

class Pairing(unittest.TestCase):
    def setUp(self):self.db=load(SCENARIO)
    def tearDown(self):self.db.close()

    def test_pairing_uses_each_forecast_window(self):
        group=at(self.db,'2026-08-01T00:00:00+00:00')['lowland-A']
        self.assertEqual(group['status'],'关注')
        self.assertEqual([day['date'] for day in group['days']],['2026-08-02','2026-08-03','2026-08-04'])
        # 雨量按三日累计折算，潮位顶托削减排水能力，未把两个峰值直接相加
        self.assertEqual(group['days'][0]['rain_mm'],60)
        self.assertLess(group['days'][0]['effective_drainage_mm_per_day'],group['days'][0]['drainage_mm_per_day'])
        self.assertEqual(group['windows'][0]['start'],'2026-08-02')

    def test_unpaired_day_reported_not_assumed_safe(self):
        group=at(self.db,'2026-08-01T00:00:00+00:00')['lowland-A']
        reasons=[item['reason'] for item in group['unable']]
        self.assertTrue(any('不重合' in reason and '2026-08-06' in reason for reason in reasons))
        self.assertEqual(group['coverage']['unpaired_days'],1)
        self.assertEqual(group['windows'][0]['end_basis'],'次日资料缺失，窗口终点未定')

    def test_missing_streams_mean_unable(self):
        group=at(self.db,'2026-08-01T00:00:00+00:00')['lowland-B']
        self.assertEqual(group['status'],'无法判断')
        self.assertEqual(group['windows'],[])
        self.assertIn('缺少雨量、排水工况资料',group['unable'][0]['reason'])

    def test_missing_drainage_update_changes_decision(self):
        before=at(self.db,'2026-08-01T00:00:00+00:00')['lowland-C']
        after=at(self.db,'2026-09-01T00:00:00+00:00')['lowland-C']
        self.assertEqual((before['status'],after['status']),('常态','关注'))
        self.assertEqual(after['days'][0]['effective_drainage_mm_per_day'],10)
        self.assertEqual(after['windows'][0]['action'],'组织避险')

class Revision(unittest.TestCase):
    def setUp(self):self.db=load(SCENARIO)
    def tearDown(self):self.db.close()

    def test_new_forecast_preserves_old_basis_and_names_triggers(self):
        a,b,c=[generate(self.db,t) for t in SCENARIO['known_at']]
        change=difference(a,b)
        later=difference(b,c)
        review={item['region']:item for item in change['review']}
        self.assertEqual(list(review),['lowland-A'])
        self.assertEqual(review['lowland-A']['basis_before']['fingerprint'],a['fingerprint'])
        self.assertIn('避险窗口变化',[trigger['change'] for trigger in review['lowland-A']['triggers']])
        # 排水能力更新后递减的街区从常态转为关注，需要复议并保留当时依据
        updated={item['region']:item for item in later['review']}
        self.assertEqual(updated['lowland-C']['status_before'],'常态')
        self.assertEqual(updated['lowland-C']['status_after'],'关注')
        self.assertEqual(updated['lowland-C']['basis_before']['fingerprint'],b['fingerprint'])
        self.assertIn('状态变化',[trigger['change'] for trigger in updated['lowland-C']['triggers']])
        self.assertEqual(change['before']['fingerprint'],a['fingerprint'])
        self.assertEqual(a['decisions'],generate(self.db,SCENARIO['known_at'][0])['decisions'])

    def test_unable_is_carried_forward(self):
        a,b,c=[generate(self.db,t) for t in SCENARIO['known_at']]
        change=difference(a,b)
        later=difference(b,c)
        self.assertEqual([item['region'] for item in change['previously_unable']],['lowland-B'])
        self.assertTrue(all(d['status']!='常态' or not d['unable'] for d in b['decisions']))

class Gaps(unittest.TestCase):
    def test_threshold_without_tide_handling_is_unable(self):
        base={'known_at':['2026-08-10T00:00:00+00:00'],'documents':[]}
        def doc(source,identity,records,received='2026-07-01T00:00:00+00:00'):
            return {'source':source,'document_id':identity,'revision':'r1','received_at':received,'records':records}
        body={'metric':'flood','region':'x','unit':'m'}
        base['documents']=[
            doc('t','tide',[{'kind':'tide','id':'t','revision':'r1','valid_from':'2026-08-02','valid_to':'2026-08-02',
                 'payload':dict(body,height_m=3.0)}]),
            doc('r','rain',[{'kind':'rainfall','id':'r','revision':'r1','valid_from':'2026-08-02','valid_to':'2026-08-02',
                 'payload':dict(body,amount_mm=100)}]),
            doc('d','drain',[{'kind':'drainage','id':'d','revision':'r1','valid_from':'2026-08-02','valid_to':'2026-08-02',
                 'payload':dict(body,capacity_mm_per_day=50)}]),
            doc('s','rule',[{'kind':'threshold','id':'s','revision':'r1','valid_from':'2026-08-01','valid_to':'2026-08-31',
                 'payload':dict(body,threshold_mm=20)}])]
        db=load(base)
        try:
            group=assess(db,'2026-08-10T00:00:00+00:00')[0]
            self.assertEqual(group['status'],'无法判断')
            self.assertTrue(any('潮位如何参与判定' in item['reason'] for item in group['unable']))
        finally:db.close()

    def test_known_at_hides_later_revision(self):
        db=load(SCENARIO)
        try:
            before=at(db,'2026-08-01T00:00:00+00:00')['lowland-C']
            self.assertEqual(before['days'][0]['drainage_mm_per_day'],45)
        finally:db.close()

if __name__=='__main__':unittest.main()
