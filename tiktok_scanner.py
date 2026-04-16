#!/usr/bin/env python3
"""
tiktok_scanner.py — Scanner de canais TikTok.
Baixa videos novos via yt-dlp e coloca em imports/ para o import_worker processar.
"""

import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
IMPORTS_DIR = os.path.join(PROJECT_ROOT, 'imports')

sys.path.insert(0, PROJECT_ROOT)
import db


def log(msg):
    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}', flush=True)


def _build_tiktok_url(handle):
    """Build TikTok profile URL from handle."""
    handle = handle.strip()
    if handle.startswith('http'):
        return handle
    if not handle.startswith('@'):
        handle = '@' + handle
    return f'https://www.tiktok.com/{handle}'


def scan_channel(channel):
    """List videos from a TikTok channel using yt-dlp flat playlist.
    Returns list of dicts: [{id, title, url, timestamp, upload_date}]
    """
    handle = channel['handle']
    url = _build_tiktok_url(handle)
    data_desde = channel.get('data_desde', '')
    max_videos = channel.get('max_por_scan', 2)

    log(f'  Scanning TikTok: {handle} (desde={data_desde})')

    # Scan a generous window: 200 videos max to find new ones that aren't downloaded yet
    try:
        result = subprocess.run(
            ['yt-dlp', '--flat-playlist', '-j', '--no-warnings', '--playlist-end', '200', url],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            log(f'  yt-dlp erro: {result.stderr[:200]}')
            return []
    except subprocess.TimeoutExpired:
        log(f'  yt-dlp timeout para {handle}')
        return []

    videos = []
    total_scanned = 0
    total_before_date = 0
    total_already_dl = 0

    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        vid_id = info.get('id', '')
        if not vid_id:
            continue

        total_scanned += 1

        # Filter by date
        upload_date = info.get('upload_date', '')  # YYYYMMDD format
        if data_desde and upload_date:
            desde_fmt = data_desde.replace('-', '')
            if upload_date < desde_fmt:
                total_before_date += 1
                continue

        # Skip already downloaded
        if db.is_tiktok_downloaded(vid_id):
            total_already_dl += 1
            continue

        videos.append({
            'id': vid_id,
            'title': info.get('title', ''),
            'url': info.get('url', '') or info.get('webpage_url', '') or f'https://www.tiktok.com/@{handle}/video/{vid_id}',
            'upload_date': upload_date,
            'duration': info.get('duration', 0),
        })

    # Sort oldest first (so we process in chronological order)
    videos.sort(key=lambda v: v.get('upload_date', ''))
    videos = videos[:max_videos]

    log(f'  Scan: {total_scanned} escaneados, {total_already_dl} ja baixados, {total_before_date} antes de {data_desde}, {len(videos)} selecionados')
    return videos


def download_videos(videos, channel):
    """Download TikTok videos into a daily folder and update manifest.
    Returns dict: {folder, downloaded, errors}
    """
    handle = channel['handle'].strip().lstrip('@')
    today = datetime.now().strftime('%Y%m%d')
    folder_name = f'tiktok_{handle}_{today}'
    folder_path = os.path.join(IMPORTS_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Load existing manifest if folder already has one (appending to daily batch)
    manifest_path = os.path.join(folder_path, 'manifest.json')
    existing_clips = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                raw = json.load(f)
            existing_clips = raw.get('clips', []) if isinstance(raw, dict) else raw
        except Exception:
            pass

    downloaded = []
    errors = 0

    for video in videos:
        vid_id = video['id']
        title = video['title'] or f'tiktok_{vid_id}'
        video_url = video['url']

        # Skip if already in this folder
        if any(vid_id in c.get('file', '') for c in existing_clips):
            continue

        log(f'  Baixando: {title[:50]} ({vid_id})')

        try:
            out_template = os.path.join(folder_path, f'{vid_id}.%(ext)s')
            result = subprocess.run(
                ['yt-dlp', '-o', out_template, '--no-warnings',
                 '--format', 'best[ext=mp4]/best',
                 '--merge-output-format', 'mp4',
                 video_url],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                log(f'  Download falhou para {vid_id}: {result.stderr[:200]}')
                errors += 1
                continue

            # Find the downloaded file
            mp4_file = None
            for f in os.listdir(folder_path):
                if f.startswith(vid_id) and f.endswith('.mp4'):
                    mp4_file = f
                    break

            if not mp4_file:
                log(f'  Arquivo nao encontrado apos download: {vid_id}')
                errors += 1
                continue

            downloaded.append({
                'file': mp4_file,
                'title': title,
                'tiktok_id': vid_id,
                'duration': video.get('duration', 0),
            })

            # Mark as downloaded
            db.mark_tiktok_downloaded(vid_id, channel['handle'])

        except subprocess.TimeoutExpired:
            log(f'  Timeout ao baixar {vid_id}')
            errors += 1
        except Exception as e:
            log(f'  Erro ao baixar {vid_id}: {e}')
            errors += 1

    # Update manifest (append new clips to existing)
    if downloaded:
        all_clips = existing_clips + [
            {
                'file': d['file'],
                'title': d['title'],
                'description': '',
                'tags': ['tiktok', handle],
            }
            for d in downloaded
        ]
        manifest = {
            'titulo': f'TikTok @{handle}',
            'privacy': 'public',
            'clips': all_clips
        }
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        log(f'  Manifest criado: {folder_name} ({len(downloaded)} clips)')
    else:
        # Remove empty folder
        try:
            os.rmdir(folder_path)
        except OSError:
            pass

    return {'folder': folder_name, 'downloaded': len(downloaded), 'errors': errors}


def process_all_channels(config=None):
    """Scan all active TikTok channels and download new videos.
    Returns list of results per channel.
    """
    channels = db.get_tiktok_channels()
    active = [c for c in channels if c.get('ativo', 0) == 1]

    if not active:
        log('  Nenhum canal TikTok ativo')
        return []

    log(f'  {len(active)} canal(is) TikTok ativo(s)')
    results = []

    for channel in active:
        handle = channel['handle']
        try:
            # Scan for new videos
            videos = scan_channel(channel)
            if not videos:
                results.append({'handle': handle, 'downloaded': 0, 'errors': 0, 'ok': True})
                continue

            # Download and create import folder
            result = download_videos(videos, channel)
            result['handle'] = handle
            result['ok'] = True
            results.append(result)

            # Update channel stats
            db.update_tiktok_channel(channel['id'],
                ultimo_scan=datetime.now().strftime('%Y-%m-%d %H:%M'),
                total_baixados=channel.get('total_baixados', 0) + result['downloaded']
            )

        except Exception as e:
            log(f'  Erro no canal {handle}: {e}')
            results.append({'handle': handle, 'downloaded': 0, 'errors': 1, 'ok': False, 'motivo': str(e)})

    total = sum(r.get('downloaded', 0) for r in results)
    log(f'  TikTok scan concluido: {total} video(s) baixado(s)')

    # Auto-process imports so they appear in the dashboard immediately
    if total > 0:
        try:
            import import_worker
            import_results = import_worker.process_imports(config)
            processed = [r for r in import_results if r.get('ok')]
            if processed:
                log(f'  Import worker: {len(processed)} lote(s) processado(s)')
        except Exception as e:
            log(f'  Import worker erro: {e}')

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if action == 'scan':
        results = process_all_channels()
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif action == 'list':
        channels = db.get_tiktok_channels()
        for c in channels:
            print(f'  [{c["id"]}] {c["handle"]} ({"ativo" if c["ativo"] else "inativo"}) desde={c["data_desde"]} max={c["max_por_scan"]} baixados={c["total_baixados"]}')
    elif action == 'add':
        handle = sys.argv[2] if len(sys.argv) > 2 else ''
        if not handle:
            print('Uso: tiktok_scanner.py add @handle')
            sys.exit(1)
        row_id = db.add_tiktok_channel(handle)
        print(f'Canal adicionado: {handle} (id={row_id})')
    else:
        print(f'Uso: {sys.argv[0]} scan | list | add @handle')
