"""保存已知时点的分析，比较版本变化并保留当时依据。"""
import hashlib,json
from .analysis import assess

def _decision(group):
    actions=sorted({window['action'] for window in group['windows'] if window.get('action')})
    return {'region':group['region'],'metric':group['metric'],'status':group['status'],
            'action':actions[0] if len(actions)==1 else None,
            'actions':actions,'windows':group['windows'],'unable':group['unable'],
            'coverage':group['coverage'],'sources':group['sources']}

def generate(db,known_at):
    """形成报告；报告本身即当时依据的快照。"""
    groups=assess(db,known_at)
    out={'known_at':known_at,'decisions':[_decision(group) for group in groups]}
    out['unable']=[{'region':decision['region'],'metric':decision['metric'],'reason':item['reason']}
                   for decision in out['decisions'] for item in decision['unable']]
    out['fingerprint']=hashlib.sha256(json.dumps(out,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return out

def _key(decision):
    region=decision['region'] if decision['region'] is not None else '未归属'
    metric=decision['metric'] if decision['metric'] is not None else '未归属'
    return f'{region}/{metric}'

def _window_text(windows):
    return [{'start':w['start'],'end':w['end'],'action':w.get('action'),
             'peak_depth_mm':w.get('peak_depth_mm'),'threshold_mm':w.get('threshold_mm')}
            for w in windows]

def difference(before,after):
    """逐街区比较，列出需要复议的街区、触发变化及原先建议的依据。"""
    old={_key(decision):decision for decision in before['decisions']}
    new={_key(decision):decision for decision in after['decisions']}
    review=[];changed=[]
    for key in sorted(old.keys()|new.keys()):
        a=old.get(key);b=new.get(key)
        if a==b:continue
        changed.append(key)
        triggers=[]
        if a is None:triggers.append({'change':'新增街区判断','after':b['status']})
        elif b is None:triggers.append({'change':'街区判断消失','before':a['status']})
        else:
            if a['status']!=b['status']:triggers.append({'change':'状态变化','before':a['status'],'after':b['status']})
            wa=_window_text(a['windows']);wb=_window_text(b['windows'])
            if wa!=wb:triggers.append({'change':'避险窗口变化','before':wa,'after':wb})
            ua=[item['reason'] for item in a['unable']];ub=[item['reason'] for item in b['unable']]
            if ua!=ub:triggers.append({'change':'无法判断的原因变化','before':ua,'after':ub})
            if a['sources']!=b['sources']:triggers.append({'change':'依据来源变化','before':a['sources'],'after':b['sources']})
            if a['coverage']!=b['coverage']:triggers.append({'change':'资料覆盖变化','before':a['coverage'],'after':b['coverage']})
        if not triggers:triggers.append({'change':'判断细节变化'})
        review.append({'region':b['region'] if b else a['region'],
                       'metric':b['metric'] if b else a['metric'],
                       'status_before':a['status'] if a else None,'status_after':b['status'] if b else None,
                       'actions_before':a['actions'] if a else [],'actions_after':b['actions'] if b else [],
                       'triggers':triggers,
                       'basis_before':None if a is None else {'known_at':before['known_at'],
                           'fingerprint':before['fingerprint'],'windows':a['windows'],
                           'unable':a['unable'],'sources':a['sources']},
                       'basis_after':None if b is None else {'known_at':after['known_at'],
                           'fingerprint':after['fingerprint'],'windows':b['windows'],
                           'unable':b['unable'],'sources':b['sources']}})
    return {'before':{'known_at':before['known_at'],'fingerprint':before['fingerprint']},
            'after':{'known_at':after['known_at'],'fingerprint':after['fingerprint']},
            'changed':changed,'review':review,
            'previously_unable':[{'region':d['region'],'metric':d['metric'],
                'reasons':[item['reason'] for item in d['unable']]}
                for d in before['decisions'] if d['status']=='无法判断']}
