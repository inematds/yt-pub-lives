"""
db.py — SQLite local database for yt-pub-lives.
Replaces Google Sheets as the data store for CONFIG, LIVES, and PUBLICADOS.
"""

import os
import sqlite3
import threading

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(PROJECT_ROOT, 'data')
DB_PATH = os.path.join(DB_DIR, 'lives.db')

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS lives (
    video_id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL DEFAULT '',
    data_live TEXT NOT NULL DEFAULT '',
    duracao_min TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    status_transcricao TEXT NOT NULL DEFAULT 'pendente',
    status_cortes TEXT NOT NULL DEFAULT 'pendente',
    qtd_clips TEXT NOT NULL DEFAULT '0',
    clips_publicados TEXT NOT NULL DEFAULT '0',
    clips_pendentes TEXT NOT NULL DEFAULT '0',
    data_sync TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    data_corte TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tiktok_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    data_desde TEXT NOT NULL DEFAULT '',
    max_por_scan INTEGER NOT NULL DEFAULT 2,
    ultimo_scan TEXT NOT NULL DEFAULT '',
    total_baixados INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tiktok_downloaded (
    tiktok_id TEXT PRIMARY KEY,
    channel_handle TEXT NOT NULL DEFAULT '',
    downloaded_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS publicados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_video_id TEXT NOT NULL DEFAULT '',
    clip_titulo TEXT NOT NULL DEFAULT '',
    clip_url TEXT NOT NULL DEFAULT '',
    live_video_id TEXT NOT NULL DEFAULT '',
    live_titulo TEXT NOT NULL DEFAULT '',
    data_publicacao TEXT NOT NULL DEFAULT '',
    privacy TEXT NOT NULL DEFAULT '',
    duracao TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    categoria TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT ''
);
"""

# --------------- Connection ---------------

def get_db():
    """Get thread-local SQLite connection. Auto-creates DB and tables."""
    db = getattr(_local, 'db', None)
    if db is None:
        os.makedirs(DB_DIR, exist_ok=True)
        db = sqlite3.connect(DB_PATH, timeout=10)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=5000')
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        _local.db = db
    return db


def close_db():
    """Close thread-local connection."""
    db = getattr(_local, 'db', None)
    if db:
        db.close()
        _local.db = None


# --------------- CONFIG ---------------

def load_config():
    """Load all config as dict."""
    db = get_db()
    rows = db.execute('SELECT chave, valor FROM config').fetchall()
    return {r['chave']: r['valor'] for r in rows}


def get_config(key, default=''):
    """Get single config value."""
    db = get_db()
    row = db.execute('SELECT valor FROM config WHERE chave=?', (key,)).fetchone()
    return row['valor'] if row else default


def set_config(key, value):
    """Set single config value (upsert)."""
    db = get_db()
    db.execute('INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)', (key, str(value)))
    db.commit()


def update_config(data):
    """Batch upsert config from dict."""
    db = get_db()
    for k, v in data.items():
        db.execute('INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)', (k, str(v)))
    db.commit()


# --------------- LIVES ---------------

LIVES_COLUMNS = [
    'video_id', 'titulo', 'data_live', 'duracao_min', 'url',
    'status_transcricao', 'status_cortes', 'qtd_clips',
    'clips_publicados', 'clips_pendentes', 'data_sync', 'observacoes',
    'data_corte'
]


def get_lives():
    """Get all lives sorted by data_live (oldest first)."""
    db = get_db()
    rows = db.execute('SELECT * FROM lives ORDER BY data_live ASC').fetchall()
    return [dict(r) for r in rows]


def get_live(video_id):
    """Get single live by video_id."""
    db = get_db()
    row = db.execute('SELECT * FROM lives WHERE video_id=?', (video_id,)).fetchone()
    return dict(row) if row else None


def add_lives(lives_list):
    """Insert multiple lives (ignore duplicates)."""
    db = get_db()
    for live in lives_list:
        cols = [c for c in LIVES_COLUMNS if c in live]
        placeholders = ','.join(['?'] * len(cols))
        col_names = ','.join(cols)
        vals = [str(live.get(c, '')) for c in cols]
        db.execute(f'INSERT OR IGNORE INTO lives ({col_names}) VALUES ({placeholders})', vals)
    db.commit()


def update_live(video_id, **fields):
    """Update specific fields of a live."""
    if not fields:
        return
    db = get_db()
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = [str(v) for v in fields.values()] + [video_id]
    db.execute(f'UPDATE lives SET {sets} WHERE video_id=?', vals)
    db.commit()


def delete_live(video_id):
    """Delete a live by video_id."""
    db = get_db()
    db.execute('DELETE FROM lives WHERE video_id=?', (video_id,))
    db.commit()


# --------------- PUBLICADOS ---------------

PUBLICADOS_COLUMNS = [
    'clip_video_id', 'clip_titulo', 'clip_url', 'live_video_id', 'live_titulo',
    'data_publicacao', 'privacy', 'duracao', 'tags', 'categoria', 'filename'
]


def get_publicados(live_video_id=None):
    """Get published clips, optionally filtered by live_video_id."""
    db = get_db()
    if live_video_id:
        rows = db.execute('SELECT * FROM publicados WHERE live_video_id=? ORDER BY id', (live_video_id,)).fetchall()
    else:
        rows = db.execute('SELECT * FROM publicados ORDER BY id').fetchall()
    return [dict(r) for r in rows]


def add_publicado(data):
    """Insert a published clip. Returns the new row id."""
    db = get_db()
    cols = [c for c in PUBLICADOS_COLUMNS if c in data]
    placeholders = ','.join(['?'] * len(cols))
    col_names = ','.join(cols)
    vals = [str(data.get(c, '')) for c in cols]
    cursor = db.execute(f'INSERT INTO publicados ({col_names}) VALUES ({placeholders})', vals)
    db.commit()
    return cursor.lastrowid


def update_publicado(row_id, **fields):
    """Update specific fields of a publicado by row id."""
    if not fields:
        return
    db = get_db()
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = [str(v) for v in fields.values()] + [row_id]
    db.execute(f'UPDATE publicados SET {sets} WHERE id=?', vals)
    db.commit()


def update_publicado_by_clip_id(clip_video_id, **fields):
    """Update publicado by clip_video_id (for privacy changes etc)."""
    if not fields:
        return
    db = get_db()
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = [str(v) for v in fields.values()] + [clip_video_id]
    db.execute(f'UPDATE publicados SET {sets} WHERE clip_video_id=?', vals)
    db.commit()


def delete_publicado(clip_video_id):
    """Delete publicado(s) by clip_video_id."""
    db = get_db()
    db.execute('DELETE FROM publicados WHERE clip_video_id=?', (clip_video_id,))
    db.commit()


def delete_publicado_by_id(row_id):
    """Delete publicado by row id."""
    db = get_db()
    db.execute('DELETE FROM publicados WHERE id=?', (row_id,))
    db.commit()


def clear_erro_publicados(clip_titulo):
    """Remove erro_upload/publicando/empty entries for a given titulo. Returns count deleted."""
    db = get_db()
    cursor = db.execute(
        "DELETE FROM publicados WHERE clip_titulo=? AND clip_video_id IN ('erro_upload', 'publicando', '')",
        (clip_titulo,)
    )
    db.commit()
    return cursor.rowcount


def cleanup_publicados():
    """Remove empty rows, dedup erro_upload, dedup published clips. Returns counts."""
    db = get_db()

    # Count before
    total_before = db.execute('SELECT COUNT(*) FROM publicados').fetchone()[0]

    # Remove completely empty rows
    db.execute("DELETE FROM publicados WHERE clip_video_id='' AND clip_titulo='' AND live_video_id=''")

    # Remove duplicate erro_upload (keep lowest id per titulo)
    db.execute("""
        DELETE FROM publicados WHERE id NOT IN (
            SELECT MIN(id) FROM publicados WHERE clip_video_id='erro_upload' GROUP BY clip_titulo
        ) AND clip_video_id='erro_upload'
    """)

    # Remove duplicate published clips (keep lowest id per titulo, excluding erro/empty)
    db.execute("""
        DELETE FROM publicados WHERE id NOT IN (
            SELECT MIN(id) FROM publicados
            WHERE clip_video_id NOT IN ('erro_upload', 'publicando', '')
            GROUP BY clip_titulo
        ) AND clip_video_id NOT IN ('erro_upload', 'publicando', '')
        AND clip_titulo != ''
    """)

    db.commit()
    total_after = db.execute('SELECT COUNT(*) FROM publicados').fetchone()[0]

    return {
        'total_removed': total_before - total_after,
        'remaining': total_after
    }


# --------------- TIKTOK CHANNELS ---------------

def get_tiktok_channels():
    """Get all TikTok channels."""
    db = get_db()
    rows = db.execute('SELECT * FROM tiktok_channels ORDER BY id').fetchall()
    return [dict(r) for r in rows]


def add_tiktok_channel(handle, nome='', ativo=1, data_desde='', max_por_scan=2):
    """Add a TikTok channel. Returns the new row id."""
    db = get_db()
    cursor = db.execute(
        'INSERT INTO tiktok_channels (handle, nome, ativo, data_desde, max_por_scan) VALUES (?, ?, ?, ?, ?)',
        (handle, nome, ativo, data_desde, max_por_scan)
    )
    db.commit()
    return cursor.lastrowid


def update_tiktok_channel(channel_id, **fields):
    """Update specific fields of a TikTok channel."""
    if not fields:
        return
    db = get_db()
    sets = ', '.join(f'{k}=?' for k in fields)
    vals = list(fields.values()) + [channel_id]
    db.execute(f'UPDATE tiktok_channels SET {sets} WHERE id=?', vals)
    db.commit()


def delete_tiktok_channel(channel_id):
    """Delete a TikTok channel."""
    db = get_db()
    db.execute('DELETE FROM tiktok_channels WHERE id=?', (channel_id,))
    db.commit()


# --------------- TIKTOK DOWNLOADED ---------------

def is_tiktok_downloaded(tiktok_id):
    """Check if a TikTok video was already downloaded."""
    db = get_db()
    row = db.execute('SELECT 1 FROM tiktok_downloaded WHERE tiktok_id=?', (tiktok_id,)).fetchone()
    return row is not None


def mark_tiktok_downloaded(tiktok_id, channel_handle=''):
    """Mark a TikTok video as downloaded."""
    db = get_db()
    from datetime import datetime
    db.execute(
        'INSERT OR IGNORE INTO tiktok_downloaded (tiktok_id, channel_handle, downloaded_at) VALUES (?, ?, ?)',
        (tiktok_id, channel_handle, datetime.now().strftime('%Y-%m-%d %H:%M'))
    )
    db.commit()


# --------------- Raw table access (for sheet editor UI) ---------------

TABLE_COLUMNS = {
    'CONFIG': ['chave', 'valor'],
    'LIVES': LIVES_COLUMNS,
    'PUBLICADOS': PUBLICADOS_COLUMNS,
}


def get_table_as_rows(table_name):
    """Returns header + data rows as list-of-lists (for sheet editor compatibility)."""
    table_name = table_name.upper()
    columns = TABLE_COLUMNS.get(table_name)
    if not columns:
        return []
    db = get_db()
    col_str = ','.join(columns)
    rows = db.execute(f'SELECT {col_str} FROM {table_name.lower()}').fetchall()
    result = [columns]
    for row in rows:
        result.append([str(row[i]) if row[i] is not None else '' for i in range(len(columns))])
    return result


def replace_table(table_name, rows):
    """Full table replace from list-of-lists (header + data). For sheet upload/edit."""
    table_name = table_name.upper()
    columns = TABLE_COLUMNS.get(table_name)
    if not columns or len(rows) < 1:
        return

    db = get_db()
    db.execute(f'DELETE FROM {table_name.lower()}')

    # First row is header — map columns
    header = rows[0] if rows else columns
    col_map = []
    for h in header:
        h_clean = h.strip().lower()
        if h_clean in columns:
            col_map.append(h_clean)
        else:
            col_map.append(None)

    for row in rows[1:]:
        data = {}
        for i, val in enumerate(row):
            if i < len(col_map) and col_map[i]:
                data[col_map[i]] = str(val) if val else ''
        if not data:
            continue

        if table_name == 'CONFIG':
            if 'chave' in data and data['chave']:
                db.execute('INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)',
                           (data['chave'], data.get('valor', '')))
        elif table_name == 'LIVES':
            if 'video_id' in data and data['video_id']:
                valid_cols = [c for c in data if c in LIVES_COLUMNS]
                col_names = ','.join(valid_cols)
                placeholders = ','.join(['?'] * len(valid_cols))
                vals = [data[c] for c in valid_cols]
                db.execute(f'INSERT OR REPLACE INTO lives ({col_names}) VALUES ({placeholders})', vals)
        elif table_name == 'PUBLICADOS':
            valid_cols = [c for c in data if c in PUBLICADOS_COLUMNS]
            if valid_cols:
                col_names = ','.join(valid_cols)
                placeholders = ','.join(['?'] * len(valid_cols))
                vals = [data[c] for c in valid_cols]
                db.execute(f'INSERT INTO publicados ({col_names}) VALUES ({placeholders})', vals)

    db.commit()
