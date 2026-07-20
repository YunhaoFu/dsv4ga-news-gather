#!/usr/bin/env python3
"""
统计所有 UP 主的全部视频，找出 DeepSeek V4 灰测相关但未被收录的视频
使用 WBI 签名调用 B 站 API
"""

import requests, hashlib, time, json, os, sys, urllib.parse
from functools import reduce
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
})

# Cache WBI keys
_WBI_KEYS = None

def get_wbi_keys():
    global _WBI_KEYS
    if _WBI_KEYS:
        return _WBI_KEYS
    r = SESSION.get('https://api.bilibili.com/x/web-interface/nav', timeout=10)
    wbi = r.json()['data']['wbi_img']
    img_key = wbi['img_url'].split('/')[-1].split('.')[0]
    sub_key = wbi['sub_url'].split('/')[-1].split('.')[0]
    _WBI_KEYS = (img_key, sub_key)
    return _WBI_KEYS

def get_mixin_key(orig):
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

def enc_wbi(params):
    img_key, sub_key = get_wbi_keys()
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())
    params['wts'] = curr_time
    params = dict(sorted(params.items()))
    params = {k: ''.join(filter(lambda chr: chr not in "!'()*", str(v))) for k, v in params.items()}
    query = urllib.parse.urlencode(params)
    params['w_rid'] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params

def get_up_videos(mid, max_retries=3):
    """获取某 UP 主的所有视频列表，返回 (视频列表, 总计数量)"""
    all_videos = []
    total = 0
    
    for pn in range(1, 5):
        for attempt in range(max_retries):
            try:
                time.sleep(3)
                params = enc_wbi({'mid': str(mid), 'ps': '30', 'pn': str(pn)})
                r = SESSION.get('https://api.bilibili.com/x/space/wbi/arc/search', 
                               params=params, timeout=10)
                data = r.json()
                if data.get('code') == 0:
                    vlist = data['data']['list']['vlist']
                    total = data['data']['page'].get('count', 0)
                    all_videos.extend(vlist)
                    if len(vlist) < 30:
                        return all_videos, total
                    break
                elif data.get('code') == -352:
                    # WBI signature error - refresh keys and retry
                    global _WBI_KEYS
                    _WBI_KEYS = None
                    time.sleep(5)
                    continue
                else:
                    print(f"    API error: {data.get('message','')}")
                    time.sleep(5)
                    continue
            except Exception as e:
                print(f"    Exception: {e}")
                time.sleep(5)
                continue
        else:
            print(f"    Failed after {max_retries} retries for page {pn}")
            break
    
    return all_videos, total

def is_dsv4_video(title):
    """判断视频是否与 DSv4 灰测相关"""
    tl = title.lower()
    return 'deepseek' in tl and ('灰' in title or '正式' in title)

def main():
    # Step 1: 从现有 data 文件获取所有 UP 主信息
    print("="*60)
    print("第1步: 读取现有数据中的 UP 主信息")
    print("="*60)
    
    up_dict = {}  # mid -> {name, bvids_set}
    our_bvids = set()
    
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(DATA_DIR, fname)
        try:
            with open(fpath) as f:
                d = json.load(f)
        except:
            continue
        if 'error' in d:
            continue
        bvid = d.get('bvid', '')
        up_mid = str(d.get('up_mid', ''))
        up_name = d.get('up_name', '')
        if not up_mid:
            continue
        
        our_bvids.add(bvid)
        if up_mid not in up_dict:
            up_dict[up_mid] = {'name': up_name, 'bvids': set()}
        up_dict[up_mid]['bvids'].add(bvid)
    
    print(f"  现有视频: {len(our_bvids)} 个")
    print(f"  UP 主数量: {len(up_dict)} 个")
    print(f"  UP 主列表:")
    for mid, info in sorted(up_dict.items(), key=lambda x: -len(x[1]['bvids'])):
        print(f"    {info['name']} (mid={mid}): {len(info['bvids'])} 个视频")
    
    # Step 2: 遍历每个 UP 主，获取完整视频列表
    print(f"\n{'='*60}")
    print("第2步: 遍历所有 UP 主，查找遗漏")
    print("="*60)
    
    total_missing = []
    
    for mid, info in sorted(up_dict.items(), key=lambda x: -len(x[1]['bvids'])):
        name = info['name']
        existing_bvids = info['bvids']
        
        print(f"\n▶ {name} (mid={mid})")
        print(f"  已收录: {len(existing_bvids)} 个视频")
        
        all_videos, total_count = get_up_videos(mid)
        if not all_videos:
            print(f"  获取失败，跳过")
            continue
        
        print(f"  空间总数: {total_count} 个视频")
        
        # 找出 DSv4 相关但未收录的
        missing = []
        for v in all_videos:
            title = v['title'].replace('<em class="keyword">', '').replace('</em>', '')
            bvid = v.get('bvid', '')
            if is_dsv4_video(title) and bvid not in existing_bvids and bvid not in our_bvids:
                dt = datetime.fromtimestamp(v['created'], tz=BJT)
                missing.append({
                    'bvid': bvid,
                    'title': title,
                    'time': dt.strftime('%m-%d %H:%M'),
                    'up_name': name,
                    'up_mid': mid,
                })
                our_bvids.add(bvid)  # dedup
        
        if missing:
            print(f"  ⚠ 遗漏 {len(missing)} 个 DSv4 视频:")
            for m in missing:
                print(f"    {m['time']} | {m['bvid']} | {m['title']}")
            total_missing.extend(missing)
        else:
            ds_count = sum(1 for v in all_videos if is_dsv4_video(v['title'].replace('<em class="keyword">', '').replace('</em>', '')))
            print(f"  ✓ 已全覆盖 (共 {ds_count} 个 DSv4 视频)")
    
    # Step 3: 输出汇总
    print(f"\n{'='*60}")
    print("审计结果汇总")
    print("="*60)
    print(f"\n总共发现 {len(total_missing)} 个遗漏的 DSv4 视频:")
    print()
    
    # Group by UP主
    from collections import defaultdict
    by_up = defaultdict(list)
    for m in total_missing:
        by_up[m['up_name']].append(m)
    
    for up_name, videos in sorted(by_up.items(), key=lambda x: -len(x[1])):
        print(f"  {up_name}: {len(videos)} 个遗漏")
        for v in videos:
            print(f"    {v['time']} | {v['bvid']} | {v['title']}")
    
    # Output BVIDs for extraction
    if total_missing:
        bvids_str = ' '.join([m['bvid'] for m in total_missing])
        print(f"\n{'='*60}")
        print("提取命令 (复制执行):")
        print(f"{'='*60}")
        print(f"cd {os.path.dirname(os.path.dirname(__file__))}")
        print(f"python3 scripts/bilibili_extractor.py {bvids_str} --output ./data")
    
    return total_missing

if __name__ == '__main__':
    missing = main()
