#!/usr/bin/env python3
"""
Bilibili DeepSeek V4 灰度测试视频信息提取器
===========================================
从B站视频中提取：
1. UP主信息、视频信息
2. 简介中的共享对话链接 (opncd.ai)
3. 评论区UP主回复中的下载链接/共享链接
"""

import requests
import hashlib
import time
import json
import re
import os
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))

# ---------- WBI签名工具 ----------
# 标准 B 站 WBI 签名：将 img_key+sub_key 按官方混淆表重排后取前 32 位作为 mixin_key，
# 再对参数做特殊字符过滤、排序、拼接时间戳，最后拼接 mixin_key 做 MD5。
# 注意：早期实现误用 md5(img_key+sub_key) 整串作为 mixin_key，这不是官方算法，
# 仅在部分对签名校验宽松的接口（如评论接口）侥幸可用，在严格的 WBI 接口上会失败。
_WBI_MIXIN_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]
_WBI_CACHE = {"mixin_key": None, "expires_at": 0}

def _get_mixin_key():
    now = time.time()
    if _WBI_CACHE["mixin_key"] and now < _WBI_CACHE["expires_at"]:
        return _WBI_CACHE["mixin_key"]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.bilibili.com/'
    }
    nav = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers, timeout=10)
    wbi_img = nav.json()['data']['wbi_img']
    img_key = wbi_img['img_url'].split('/')[-1].split('.')[0]
    sub_key = wbi_img['sub_url'].split('/')[-1].split('.')[0]
    orig = f"{img_key}{sub_key}"
    mixin_key = ''.join(orig[i] for i in _WBI_MIXIN_ENC_TAB)[:32]
    _WBI_CACHE["mixin_key"] = mixin_key
    _WBI_CACHE["expires_at"] = now + 3600  # cache 1 hour
    return mixin_key

def sign_params(params: dict) -> dict:
    """给B站API参数加上标准WBI签名"""
    mixin_key = _get_mixin_key()
    params = dict(sorted(params.items()))
    params['wts'] = str(int(time.time()))
    # 过滤 B 站约定的特殊字符（与官方实现一致）
    params = {k: ''.join(filter(lambda c: c not in "!'()*", str(v))) for k, v in params.items()}
    query = urllib.parse.urlencode(params)
    params['w_rid'] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
    return params

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.bilibili.com/'
}

# ---------- 标题校验 ----------

def validate_title(title: str) -> tuple:
    """
    校验视频标题是否符合 DeepSeek V4 灰度测试/正式版 主题。
    规则: 标题必须包含 "deepseek" (不区分大小写) 且包含 "灰" 或 "正式"。
    返回: (是否通过, 原因)
    """
    tl = title.lower()
    has_ds_keyword = 'deepseek' in tl or 'ds' in tl
    has_gray = '灰' in title
    has_official = '正式' in title

    if not has_ds_keyword:
        return False, f'标题不含 "DeepSeek" 或 "ds" (不区分大小写): "{title[:50]}..."'
    if not (has_gray or has_official):
        return False, f'标题不含 "灰" 或 "正式": "{title[:50]}..."'
    return True, '通过'


# ---------- 链接模式 ----------
# DeepSeek共享对话链接 (opncd.ai 或 chat.deepseek.com/share)
SHARE_PATTERNS = [
    r'https?://opncd\.ai/share/\w+',
    r'https?://chat\.deepseek\.com/share/\w+',
    r'https?://opencode\.ai/share/\w+',
]

# Code下载链接 (GitHub, Gitee, 网盘, 直链等)。
# 注意: b23.tv 短链 / bilibili opus 动态 只是视频或动态引用，并非可下载的资源，
# 不能算作下载链接，故不在此列。
# URL 字符类用 [A-Za-z0-9._~:/?&=#%+-] 显式列举，避免把 URL 后面紧跟的中文/空格
# 粘连进同一条链接 (例如 "github.com/foo这是我用..." 会变成一条脏链接)。
_URL = r'https?://[A-Za-z0-9._~:/?&=#%+-]+'
DOWNLOAD_PATTERNS = [
    r'https?://github\.com/[A-Za-z0-9._/-]+',
    r'https?://gitee\.com/[A-Za-z0-9._/-]+',
    r'https?://pan\.baidu\.com/[A-Za-z0-9._?=&]+',
    r'https?://pan\.quark\.cn/[A-Za-z0-9._?=&]+',
    r'https?://wwbcc?\.lanzou[a-z]+\.com/[A-Za-z0-9._/-]+',
    r'https?://[A-Za-z0-9.-]+\.lanzou[a-z]+\.com/[A-Za-z0-9._/-]+',
    _URL + r'\.zip',
    _URL + r'\.tar\.gz',
    _URL + r'\.dmg',
    _URL + r'\.exe',
]

def extract_urls(text: str, patterns: list) -> list:
    """从文本中提取匹配模式的URL"""
    urls = []
    for pat in patterns:
        urls.extend(re.findall(pat, text))
    return list(set(urls))

# ---------- 视频信息提取 ----------

def get_video_info(bvid_or_url: str) -> dict:
    """
    通过BVID或b23.tv短链接获取视频信息
    返回结构化视频数据
    """
    # 解析输入
    bvid = bvid_or_url
    if 'b23.tv' in bvid_or_url or 'bilibili.com' in bvid_or_url:
        r = requests.get(bvid_or_url, headers=HEADERS, allow_redirects=True, timeout=10)
        m = re.search(r'/video/(BV\w+)', r.url)
        if not m:
            return {"error": "无法从链接中提取BVID"}
        bvid = m.group(1)

    # 获取视频元数据
    r = requests.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
                     headers=HEADERS, timeout=10)
    data = r.json()
    if data.get('code') != 0:
        return {"error": f"API返回错误: {data.get('message', 'unknown')}"}

    vd = data['data']
    aid = vd['aid']
    pub_ts = vd['pubdate']

    result = {
        "bvid": bvid,
        "aid": aid,
        "title": vd['title'],
        "up_name": vd['owner']['name'],
        "up_mid": vd['owner']['mid'],
        "up_face": vd['owner'].get('face', ''),
        "desc": vd.get('desc', ''),
        "duration": vd.get('duration', 0),
        "pub_time_ts": pub_ts,
        "pub_time": datetime.fromtimestamp(pub_ts, tz=BJT).strftime('%Y-%m-%d %H:%M:%S'),
        "stats": {
            "view": vd['stat']['view'],
            "like": vd['stat']['like'],
            "coin": vd['stat']['coin'],
            "favorite": vd['stat']['favorite'],
            "share": vd['stat']['share'],
            "reply": vd['stat']['reply'],
        },
        "tags": [],
        "share_links": extract_urls(vd.get('desc', ''), SHARE_PATTERNS),
        "download_links": extract_urls(vd.get('desc', ''), DOWNLOAD_PATTERNS),
        "comments_links": {"share": [], "download": []},
    }

    # 获取标签
    try:
        tag_r = requests.get(f'https://api.bilibili.com/x/web-interface/tag/archive?bvid={bvid}',
                             headers=HEADERS, timeout=10)
        tag_data = tag_r.json()
        if tag_data.get('code') == 0:
            result['tags'] = [t['tag_name'] for t in tag_data['data']]
    except Exception:
        pass

    return result

# ---------- 评论提取 ----------

def _collect_up_reply(msg: str, reply_to: str, ctime: int, up_mid: int) -> dict:
    """从UP主的一条留言中提取链接，返回记录或None"""
    share_urls = extract_urls(msg, SHARE_PATTERNS)
    dl_urls = extract_urls(msg, DOWNLOAD_PATTERNS)
    if share_urls or dl_urls:
        return {
            "reply_to": reply_to,
            "message": msg,
            "share_links": share_urls,
            "download_links": dl_urls,
            "time": datetime.fromtimestamp(ctime, tz=BJT).strftime('%Y-%m-%d %H:%M:%S')
        }
    return None

def get_comments(aid: int, up_mid: int, max_pages: int = 5) -> dict:
    """
    获取视频评论，提取UP主本人发的所有留言中的链接
    返回: { top_comments: [], up_replies_with_links: [] }
    """
    all_replies = []
    up_replies_with_links = []
    seen_msgs = set()  # 去重

    for pn in range(1, max_pages + 1):
        params = sign_params({
            'type': '1', 'oid': str(aid), 'mode': '3', 'ps': '20', 'pn': str(pn)
        })
        try:
            r = requests.get('https://api.bilibili.com/x/v2/reply/main',
                             params=params, headers=HEADERS, timeout=10)
            cdata = r.json()
            if cdata.get('code') != 0:
                break
            data = cdata['data']

            # ☆ 关键修复: 检查置顶评论 (top_replies)
            for t in data.get('top_replies') or []:
                if int(t['member']['mid']) == up_mid:
                    msg = t['content']['message'].strip()
                    if msg not in seen_msgs:
                        seen_msgs.add(msg)
                        rec = _collect_up_reply(msg, '(UP主置顶评论)', t['ctime'], up_mid)
                        if rec:
                            up_replies_with_links.append(rec)

            replies = data.get('replies', [])
            if not replies:
                break
            all_replies.extend(replies)
            if len(replies) < 20:
                break
        except Exception:
            break

    # 分析评论列表中的UP主留言
    for r in all_replies:
        # UP主自己发的顶级评论
        if int(r['member']['mid']) == up_mid:
            msg = r['content']['message'].strip()
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                rec = _collect_up_reply(msg, '(UP主评论)', r['ctime'], up_mid)
                if rec:
                    up_replies_with_links.append(rec)

        # UP主在别人评论下的子回复
        for sub in r.get('replies') or []:
            if int(sub['member']['mid']) == up_mid:
                msg = sub['content']['message'].strip()
                if msg not in seen_msgs:
                    seen_msgs.add(msg)
                    rec = _collect_up_reply(msg, f"回复 {r['member']['uname']}", sub['ctime'], up_mid)
                    if rec:
                        up_replies_with_links.append(rec)

    # 取高赞评论
    top_comments = []
    for r in sorted(all_replies, key=lambda x: x.get('like', 0), reverse=True)[:8]:
        top_comments.append({
            "user": r['member']['uname'],
            "message": r['content']['message'][:300],
            "likes": r.get('like', 0),
            "time": datetime.fromtimestamp(r['ctime'], tz=BJT).strftime('%Y-%m-%d %H:%M:%S')
        })

    return {
        "total": len(all_replies),
        "top_comments": top_comments,
        "up_replies_with_links": up_replies_with_links,
    }

# ---------- 主流程 ----------

def extract_video(bvid_or_url: str, max_comment_pages: int = 3) -> dict:
    """对一个视频执行完整的信息提取"""
    print(f"  [提取中] 正在获取视频信息...")
    info = get_video_info(bvid_or_url)
    if "error" in info:
        print(f"  [错误] {info['error']}")
        return info

    aid = info['aid']
    up_mid = info['up_mid']
    bvid = info['bvid']

    print(f"  标题: {info['title']}")
    print(f"  UP主: {info['up_name']}")
    print(f"  发布时间: {info['pub_time']}")

    # 标题校验 - 拒绝非灰测视频
    ok, reason = validate_title(info['title'])
    if not ok:
        print(f"  ❌ [拒绝] {reason}")
        return {"error": f"标题不符合灰测主题: {reason}", "bvid": info.get('bvid'), "title": info['title']}

    # 获取评论
    print(f"  [提取中] 正在获取评论...")
    comments = get_comments(aid, up_mid, max_comment_pages)

    # 合并简介和评论中的链接
    all_share = list(info['share_links'])
    all_download = list(info['download_links'])

    for up_reply in comments['up_replies_with_links']:
        for url in up_reply['share_links']:
            if url not in all_share:
                all_share.append(url)
        for url in up_reply['download_links']:
            if url not in all_download:
                all_download.append(url)

    info['all_share_links'] = all_share
    info['all_download_links'] = all_download
    info['comments'] = comments

    print(f"  共享链接: {len(all_share)} 个")
    print(f"  下载链接: {len(all_download)} 个")
    print(f"  高赞评论: {len(comments['top_comments'])} 条")
    print(f"  UP主含链接回复: {len(comments['up_replies_with_links'])} 条")

    return info

def save_result(info: dict, output_dir: str):
    """保存提取结果为JSON和Markdown"""
    bvid = info.get('bvid', 'unknown')

    # JSON
    json_path = os.path.join(output_dir, f'{bvid}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"  [保存] JSON: {json_path}")

    # Markdown摘要
    md_path = os.path.join(output_dir, f'{bvid}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(format_markdown(info))
    print(f"  [保存] Markdown: {md_path}")

def format_markdown(info: dict) -> str:
    """格式化为Markdown"""
    lines = []
    lines.append(f"# {info.get('title', '未知标题')}")
    lines.append("")
    lines.append(f"- **BVID**: `{info.get('bvid', '?')}`")
    lines.append(f"- **UP主**: [{info.get('up_name', '?')}](https://space.bilibili.com/{info.get('up_mid', '?')})")
    lines.append(f"- **发布时间**: {info.get('pub_time', '?')}")
    lines.append(f"- **时长**: {info.get('duration', 0)}秒")
    lines.append(f"- **播放/点赞/评论**: {info.get('stats', {}).get('view', '?')} / {info.get('stats', {}).get('like', '?')} / {info.get('stats', {}).get('reply', '?')}")
    lines.append(f"- **视频链接**: [B站观看](https://www.bilibili.com/video/{info.get('bvid', '?')})")
    lines.append("")

    # 简介
    desc = info.get('desc', '')
    if desc:
        lines.append("## 📝 视频简介")
        lines.append("")
        lines.append(f"> {desc}")
        lines.append("")

    # 共享链接
    share = info.get('all_share_links', info.get('share_links', []))
    if share:
        lines.append("## 🔗 DeepSeek 对话共享链接")
        lines.append("")
        for url in share:
            lines.append(f"- [对话链接]({url})")
        lines.append("")

    # 下载链接
    download = info.get('all_download_links', info.get('download_links', []))
    if download:
        lines.append("## 📦 项目下载链接")
        lines.append("")
        for url in download:
            lines.append(f"- [{url}]({url})")
        lines.append("")

    # UP主含链接回复
    up_replies = info.get('comments', {}).get('up_replies_with_links', [])
    if up_replies:
        lines.append("## 💬 UP主评论中的链接")
        lines.append("")
        for ur in up_replies:
            lines.append(f"- **回复** {ur['reply_to']} ({ur['time']}):")
            lines.append(f"  > {ur['message']}")
            if ur.get('share_links'):
                for u in ur['share_links']:
                    lines.append(f"  - 🔗 对话: {u}")
            if ur.get('download_links'):
                for u in ur['download_links']:
                    lines.append(f"  - 📦 下载: {u}")
        lines.append("")

    # 高赞评论
    top = info.get('comments', {}).get('top_comments', [])
    if top:
        lines.append("## 🏆 高赞评论")
        lines.append("")
        for c in top:
            lines.append(f"- **{c['user']}** (👍{c['likes']}): {c['message']}")
        lines.append("")

    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='B站 DeepSeek V4 视频信息提取器')
    parser.add_argument('input', nargs='+', help='BVID 或 b23.tv 短链接')
    parser.add_argument('--output', '-o', default='./data', help='输出目录')
    parser.add_argument('--save-json', action='store_true', default=True, help='保存JSON')
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    for vid in args.input:
        print(f"\n{'='*60}")
        print(f"处理: {vid}")
        print('='*60)
        result = extract_video(vid)
        if 'error' in result:
            print(f"  ❌ 失败: {result['error']}")
        else:
            save_result(result, args.output)
            print(f"  ✅ 提取完成")
