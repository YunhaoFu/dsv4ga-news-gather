#!/usr/bin/env python3
"""
从 data/ 目录中的所有 JSON 文件重新生成 README.md
"""

import json, os, re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

BJT = timezone(timedelta(hours=8))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
README_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'README.md')

def load_all_videos():
    """加载所有视频数据，按时间排序"""
    videos = []
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(DATA_DIR, fname)) as f:
                d = json.load(f)
        except:
            continue
        if 'error' in d:
            continue
        videos.append(d)
    
    # 按发布时间排序（倒序）
    videos.sort(key=lambda v: v.get('pub_time_ts', 0), reverse=True)
    return videos

def format_readme(videos):
    lines = []
    
    up_count = len(set(v.get('up_mid') for v in videos))
    
    # 统计共享链接和下载链接
    all_share_links = []
    all_dl_links = []
    for v in videos:
        share = v.get('all_share_links', v.get('share_links', []))
        dl = v.get('all_download_links', v.get('download_links', []))
        all_share_links.extend(share)
        all_dl_links.extend(dl)
    
    # 去重
    all_share_links = list(set(all_share_links))
    all_dl_links = list(set(all_dl_links))
    
    lines.append(f"# DeepSeek V4 灰度测试 Bilibili 信息中心")
    lines.append("")
    lines.append(f"> **DeepSeek V4 正式版/灰度测试** 哔哩哔哩视频信息汇集")
    lines.append("")
    lines.append(f"`📹 灰测视频 {len(videos)}`　`👤 UP主 {up_count}`　`🔗 共享链接 {len(all_share_links)}`　`📦 下载链接 {len(all_dl_links)}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 日期分布 =====
    lines.append("## 📅 日期分布")
    lines.append("")
    
    date_count = defaultdict(int)
    for v in videos:
        ts = v.get('pub_time_ts', 0)
        dt = datetime.fromtimestamp(ts, tz=BJT)
        date_key = dt.strftime('%m-%d')
        date_count[date_key] += 1
    
    max_count = max(date_count.values()) if date_count else 1
    sorted_dates = sorted(date_count.keys())

    lines.append("| 日期 | 分布 | 数量 |")
    lines.append("|------|------|------|")

    for date in sorted_dates:
        count = date_count[date]
        bar_len = max(1, int(count / max_count * 30))
        bar = '█' * bar_len + '░' * (30 - bar_len)
        lines.append(f"| {date} | {bar} | **{count}** |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== UP主排行榜 =====
    lines.append("## 🏆 UP主排行榜")
    lines.append("")
    lines.append("| # | UP主 | 视频数 | 共享链接 | 下载链接 |")
    lines.append("|---|------|--------|----------|----------|")
    
    up_stats = defaultdict(lambda: {'count': 0, 'share': 0, 'dl': 0, 'name': ''})
    for v in videos:
        mid = v.get('up_mid', '')
        name = v.get('up_name', '')
        up_stats[mid]['count'] += 1
        up_stats[mid]['name'] = name
        share = v.get('all_share_links', v.get('share_links', []))
        dl = v.get('all_download_links', v.get('download_links', []))
        up_stats[mid]['share'] += 1 if share else 0
        up_stats[mid]['dl'] += 1 if dl else 0
    
    sorted_ups = sorted(up_stats.items(), key=lambda x: -x[1]['count'])
    
    medals = ['🥇', '🥈', '🥉']
    for i, (mid, info) in enumerate(sorted_ups):
        rank = f"{i+1}" if i >= 3 else medals[i]
        share_str = f"{info['share']}🔗" if info['share'] > 0 else "-"
        dl_str = f"{info['dl']}📦" if info['dl'] > 0 else "-"
        lines.append(f"| {rank} | [{info['name']}](https://space.bilibili.com/{mid}) | {info['count']} | {share_str} | {dl_str} |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 完整视频列表 =====
    lines.append("## 📹 完整视频列表 (按时间倒序)")
    lines.append("")
    lines.append("> 🔗 = 含共享对话链接  📦 = 含下载链接")
    lines.append("")
    lines.append("| # | 日期 | UP主 | 标题 |")
    lines.append("|---|------|------|------|")
    
    for i, v in enumerate(videos, 1):
        ts = v.get('pub_time_ts', 0)
        dt = datetime.fromtimestamp(ts, tz=BJT)
        date_str = dt.strftime('%m-%d %H:%M')
        
        up_name = v.get('up_name', '?')
        up_mid = v.get('up_mid', '?')
        title = v.get('title', '?')
        bvid = v.get('bvid', '?')
        
        share = v.get('all_share_links', v.get('share_links', []))
        dl = v.get('all_download_links', v.get('download_links', []))
        
        prefix = ""
        if share and dl:
            prefix = "🔗📦 "
        elif share:
            prefix = "🔗 "
        elif dl:
            prefix = "📦 "
        
        lines.append(f"| {i} | {date_str} | [{up_name}](https://space.bilibili.com/{up_mid}) | [{prefix}{title}](https://www.bilibili.com/video/{bvid}) |")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 解析工具 =====
    lines.append("## 🔧 解析工具")
    lines.append("")
    lines.append("> 由 UP 主 [离散性好色](https://space.bilibili.com/192177) 提供")
    lines.append("")
    lines.append("[**https://op.ovo.re/**](https://op.ovo.re/)")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 共享对话链接 =====
    lines.append(f"## 🔗 共享对话链接")
    lines.append("")
    lines.append(f"共 **{len(all_share_links)}** 个：")
    lines.append("")
    
    # 为每个共享链接找到对应的 UP 主和视频标题
    share_to_video = {}
    for v in videos:
        share = v.get('all_share_links', v.get('share_links', []))
        for url in share:
            if url not in share_to_video:
                share_to_video[url] = (v.get('up_name', '?'), v.get('up_mid', '?'), v.get('title', '?'))
    
    for url in all_share_links:
        info = share_to_video.get(url, ('?', '?', '?'))
        lines.append(f"- [{url}]({url}) — [{info[0]}](https://space.bilibili.com/{info[1]})「{info[2]}」")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 下载链接 =====
    lines.append(f"## 📦 下载链接")
    lines.append("")
    lines.append(f"共 **{len(all_dl_links)}** 个：")
    lines.append("")
    
    dl_to_video = {}
    for v in videos:
        dl = v.get('all_download_links', v.get('download_links', []))
        for url in dl:
            if url not in dl_to_video:
                dl_to_video[url] = (v.get('up_name', '?'), v.get('up_mid', '?'), v.get('title', '?'))
    
    for url in all_dl_links:
        info = dl_to_video.get(url, ('?', '?', '?'))
        lines.append(f"- [{url}]({url}) — [{info[0]}](https://space.bilibili.com/{info[1]})「{info[2]}」")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ===== 项目结构 =====
    lines.append("## 🛠 项目结构")
    lines.append("")
    lines.append("```")
    lines.append("dsv4ga-news-gather/")
    lines.append("├── README.md")
    lines.append("├── scripts/bilibili_extractor.py")
    lines.append("└── data/")
    lines.append("    ├── BV*.json")
    lines.append("    └── BV*.md")
    lines.append("```")
    
    return '\n'.join(lines)

def main():
    videos = load_all_videos()
    print(f"已加载 {len(videos)} 个视频")
    
    content = format_readme(videos)
    
    with open(README_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"已生成 README.md ({len(content)} 字符)")
    
    # Print summary
    up_names = set(v.get('up_name') for v in videos)
    print(f"\n统计:")
    print(f"  视频总数: {len(videos)}")
    print(f"  UP主数: {len(up_names)}")
    
    all_share = set()
    all_dl = set()
    for v in videos:
        all_share.update(v.get('all_share_links', v.get('share_links', [])))
        all_dl.update(v.get('all_download_links', v.get('download_links', [])))
    print(f"  共享链接: {len(all_share)}")
    print(f"  下载链接: {len(all_dl)}")

if __name__ == '__main__':
    main()
