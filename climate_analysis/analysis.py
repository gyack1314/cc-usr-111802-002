"""按各自适用时间配对潮位、雨量、排水工况与街区阈值，形成积水与避险窗口。

时间一律按自然日配对：带时刻的记录取其覆盖的日期，日期记录按闭区间覆盖。
同一街区同一指标在同一天有多份资料时取对避险最不利的一份，并在结果中留痕。
"""
from datetime import date, timedelta

from .evidence import parse_time, records

LABELS=(('tide','潮位'),('rainfall','雨量'),('drainage','排水工况'),('threshold','街区阈值'))
LABEL=dict(LABELS)

def _number(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) else None

def _window(record):
    start=parse_time(record['valid_from']).date()
    end=parse_time(record['valid_to']).date() if record.get('valid_to') else None
    if end is not None and end<start:raise ValueError('有效时间窗不合法')
    return {'start':start,'end':end}

def _covers(window,day):
    return window['start']<=day and (window['end'] is None or day<=window['end'])

def _item(kind,record):
    """把一个来源记录归一为日期窗加数值；无法比较时返回原因。"""
    window=_window(record);p=record['payload']
    if kind=='rainfall':
        depth=_number(p.get('depth_mm',p.get('rainfall_depth_mm')))
        rate=_number(p.get('amount_mm',p.get('rainfall_mm')))
        if depth is not None:
            if window['end'] is None:return None,'雨量累计值缺少有效时间窗终点，无法折算日雨量'
            days=(window['end']-window['start']).days+1
            return {'window':window,'value':depth/days},None
        if rate is not None:return {'window':window,'value':rate},None
        return None,'雨量缺少可比较的毫米数'
    if kind=='tide':
        value=_number(p.get('height_m',p.get('tide_m')))
        if value is None:return None,'潮位缺少可比较的高度（height_m）'
        return {'window':window,'value':value},None
    if kind=='drainage':
        value=_number(p.get('capacity_mm_per_day',p.get('capacity_mm')))
        if value is None:return None,'排水工况缺少可比较的排水能力（capacity_mm_per_day）'
        return {'window':window,'value':value},None
    if kind=='threshold':
        value=_number(p.get('threshold_mm',p.get('threshold')))
        if value is None:return None,'街区阈值缺少可比较的毫米阈值'
        base=_number(p.get('tide_base_m'));block=_number(p.get('tide_block_m'));alone=_number(p.get('tide_threshold_m'))
        if block is not None or base is not None:
            if base is None or block is None or block<=base:
                return None,'街区阈值的潮位顶托参数不完整（tide_base_m、tide_block_m 需同时给出且后者更大）'
            mode='backwater'
        elif alone is not None:
            mode='tide-trigger'
        else:
            return None,'街区阈值未说明潮位如何参与判定（缺 tide_base_m/tide_block_m 或 tide_threshold_m）'
        action=p.get('action')
        return {'window':window,'value':value,'mode':mode,'base':base,'block':block,
                'tide_threshold':alone,'action':action if isinstance(action,str) and action else '避险'},None
    raise ValueError(kind)

def _normalized(stream):
    items={kind:[] for kind,_ in LABELS};problems=[]
    for kind,label in LABELS:
        for record in stream.get(kind,[]):
            try:item,problem=_item(kind,record)
            except ValueError as error:item,problem=None,str(error)
            if problem:problems.append(f'{label}记录 {record["id"]}（版本 {record["revision"]}）：{problem}')
            else:item['record']=record;items[kind].append(item)
    return items,problems

def _ranges(days):
    days=sorted(set(days));out=[];start=prev=None
    for day in days:
        if start is None:start=prev=day
        elif day==prev+timedelta(days=1):prev=day
        else:out.append((start,prev));start=prev=day
    if start is not None:out.append((start,prev))
    return out

def _describe(days):
    return '、'.join(f'{a.isoformat()} 至 {b.isoformat()}' if a!=b else a.isoformat() for a,b in _ranges(days))

def _pick(items,day,label):
    """取当天适用的记录；多份时按最不利方向选择并留痕。"""
    candidates=[item for item in items if _covers(item['window'],day)]
    if not candidates:return None,None
    if label in ('潮位','雨量'):chosen=max(candidates,key=lambda item:(item['value'],item['record']['revision']))
    elif label=='排水工况':chosen=min(candidates,key=lambda item:(item['value'],item['record']['revision']))
    else:chosen=min(candidates,key=lambda item:(item['value'],item['record']['revision']))
    note=None
    if len(candidates)>1:note=f'{label}当日有多份适用资料，取最不利值'
    return chosen,note

def _span(items):
    """核对范围：从任一侧最早开始日到较晚的已知结束日，以暴露另一侧尚未开始的日期。"""
    start=min(min(item['window']['start'] for item in items['tide']),
              min(item['window']['start'] for item in items['rainfall']))
    ends=[item['window']['end'] for kind in ('rainfall','tide') for item in items[kind]
          if item['window']['end'] is not None]
    if not ends:return start,start,False
    return start,max(ends),True

def _intersection(items,start,end):
    paired=[];unpaired=[];day=start
    while day<=end and (day-start).days<=400:
        rock=any(_covers(item['window'],day) for item in items['tide'])
        rain=any(_covers(item['window'],day) for item in items['rainfall'])
        if rock and rain:paired.append(day)
        elif rock or rain:unpaired.append(day)
        day+=timedelta(days=1)
    return paired,unpaired

def _group(stream):
    items,problems=_normalized(stream)
    out={'region':None,'metric':None,'status':'无法判断','windows':[],'days':[],
         'unable':[{'reason':problem} for problem in problems],'sources':[],
         'coverage':{'from':None,'to':None,'checked_days':0,'paired_days':0,'unpaired_days':0}}
    missing=[LABEL[kind] for kind,_ in LABELS if not items[kind]]
    if missing:
        out['unable'].append({'reason':'缺少'+'、'.join(missing)+'资料，无法判断'})
        return out
    units={item['record']['payload'].get('unit') for kind,_ in LABELS for item in items[kind]}
    if None in units or not all(isinstance(unit,str) and unit for unit in units):
        out['unable'].append({'reason':'存在未标注单位的资料，无法确认可比口径'})
        return out
    if len(units)>1:
        out['unable'].append({'reason':'四类资料来源单位不一致（'+'、'.join(sorted(units))+'），无法配对'})
        return out
    modes={item['mode'] for item in items['threshold']}
    if len(modes)>1:
        out['unable'].append({'reason':'街区阈值对潮位的处理方式不一致（顶托与独立触发混用），无法判断'})
        return out
    start,end,bounded=_span(items)
    paired,unpaired=_intersection(items,start,end)
    out['coverage']={'from':start.isoformat(),'to':end.isoformat() if bounded else None,
                     'checked_days':len(paired)+len(unpaired),'paired_days':len(paired),
                     'unpaired_days':len(unpaired)}
    if not paired:
        out['unable'].append({'reason':'潮位与雨量的有效时间窗不重合，无法配对，不能把两个峰值相加'})
        return out
    if unpaired:
        out['unable'].append({'reason':f'潮位与雨量时间窗不重合的日期无法配对：{_describe(unpaired)}'})
    if not bounded:
        out['unable'].append({'reason':'潮位与雨量预报均未给出结束时间，只能核对起始日，无法确定避险窗口'})
    gaps={kind:[] for kind,_ in LABELS}
    for day in paired:
        chosen={kind:_pick(items[kind],day,LABEL[kind]) for kind,_ in LABELS}
        for kind,_ in LABELS:
            if chosen[kind][0] is None:gaps[kind].append(day)
        if any(chosen[kind][0] is None for kind,_ in LABELS):continue
        tide,rain,drain,rule=[chosen[kind][0] for kind in ('tide','rainfall','drainage','threshold')]
        notes=[note for kind,_ in LABELS for note in [chosen[kind][1]] if note]
        if rule['mode']=='backwater':
            factor=max(0.0,min(1.0,(rule['block']-tide['value'])/(rule['block']-rule['base'])))
            effective=drain['value']*factor
        else:
            effective=drain['value']
        depth=round(max(0.0,rain['value']-effective),2)
        tide_hit=rule['mode']=='tide-trigger' and tide['value']>=rule['tide_threshold']
        exceeds=depth>=rule['value'] or tide_hit
        row={'date':day.isoformat(),'rain_mm':rain['value'],'tide_m':tide['value'],
             'drainage_mm_per_day':drain['value'],'effective_drainage_mm_per_day':round(effective,2),
             'depth_mm':depth,'threshold_mm':rule['value'],'exceeds':exceeds,
             'action':rule['action'] if exceeds else None,
             'sources':[item['record']['source']['sha256'] for item in (tide,rain,drain,rule)]}
        if notes:row['note']='；'.join(notes)
        out['days'].append(row)
        out['sources'].extend(row['sources'])
    for kind,_ in LABELS:
        if gaps[kind]:out['unable'].append({'reason':f'{LABEL[kind]}资料未覆盖：{_describe(gaps[kind])}，这些日期无法判断'})
    if not out['days']:
        out['unable'].append({'reason':'没有任何一天能同时取得四类资料，无法判断'})
        return out
    for window in _windows(out['days'],set(paired),end):
        window['sources']=sorted(set(window.pop('_sources')))
        out['windows'].append(window)
    if any(day['exceeds'] for day in out['days']):out['status']='关注'
    elif out['unable']:out['status']='无法判断'
    else:out['status']='常态'
    out['sources']=sorted(set(out['sources']))
    return out

def _windows(days,checked,end):
    """把连续超阈值的日子合并为避险窗口；窗口终点只取资料真正覆盖到的最后一天。"""
    result=[];current=None
    for day in days:
        if day['exceeds']:
            if current is None:
                current={'start':day['date'],'end':day['date'],'action':day['action'],
                         'peak_depth_mm':day['depth_mm'],'threshold_mm':day['threshold_mm'],
                         'end_basis':'已核对资料','_sources':list(day['sources'])}
                result.append(current)
            else:
                current['end']=day['date']
                current['peak_depth_mm']=max(current['peak_depth_mm'],day['depth_mm'])
                current['_sources'].extend(day['sources'])
                if day['action']!=current['action']:current['action']=None
        else:current=None
    for window in result:
        last=date.fromisoformat(window['end'])
        following=last+timedelta(days=1)
        if following>end:
            window['end']=None
            window['end_basis']=f'资料止于 {last.isoformat()}，无法确认次日是否仍超阈值，窗口终点未定'
        elif following in checked:window['end_basis']='已核对次日未超阈值'
        else:window['end_basis']='次日资料缺失，窗口终点未定'
    return result

def _collect(db,known_at):
    streams={};unattributed=[]
    for kind,label in LABELS:
        for record in records(db,kind,known_at):
            p=record['payload'];region=p.get('region');metric=p.get('metric')
            if not isinstance(region,str) or not isinstance(metric,str):
                unattributed.append(f'{label}记录 {record["id"]} 缺少 region 或 metric，无法归入街区')
                continue
            streams.setdefault((region,metric),{}).setdefault(kind,[]).append(record)
    return streams,unattributed

def assess(db,known_at):
    """返回每个街区--指标的积水天、避险窗口与无法判断原因。"""
    streams,unattributed=_collect(db,known_at)
    groups=[]
    for (region,metric),stream in sorted(streams.items()):
        group=_group(stream);group['region']=region;group['metric']=metric
        groups.append(group)
    if unattributed:
        groups.append({'region':None,'metric':None,'status':'无法判断','windows':[],
            'days':[],'unable':[{'reason':reason} for reason in unattributed],'sources':[],
            'coverage':{'from':None,'to':None,'checked_days':0,'paired_days':0,'unpaired_days':0}})
    return groups
