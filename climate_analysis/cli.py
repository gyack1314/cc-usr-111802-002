"""从本地合成资料形成各已知时间的分析、当前建议和变更复议。"""
import argparse,json
from pathlib import Path
from .evidence import connect,receive
from .report import generate,difference

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['inspect'])
    parser.add_argument('input')
    args=parser.parse_args()
    data=json.loads(Path(args.input).read_text(encoding='utf8'))
    db=connect(':memory:')
    for doc in data['documents']:receive(db,doc)
    reports=[generate(db,known_at) for known_at in data['known_at']]
    history=[{'known_at':a['known_at'],'fingerprint':a['fingerprint'],
              'decisions':a['decisions'],'change':difference(a,b)}
             for a,b in zip(reports,reports[1:])]
    latest=reports[-1]
    print(json.dumps({'history':history,'current':latest},ensure_ascii=False,indent=2))
    db.close()

if __name__=='__main__':main()
