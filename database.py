import sqlite3

DB_PATH = "examiner.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER,
            text TEXT NOT NULL,
            keywords TEXT NOT NULL,
            owner_id INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticket_id INTEGER NOT NULL,
            score INTEGER,
            max_score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Миграция: добавить owner_id если его нет
    try:
        cur.execute("ALTER TABLE tickets ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()

def get_next_ticket_number(owner_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MAX(number) FROM tickets WHERE owner_id = ?", (owner_id,))
    row = cur.fetchone()
    conn.close()
    return (row[0] or 0) + 1

def save_ticket(text: str, keywords: str, owner_id: int) -> int:
    number = get_next_ticket_number(owner_id)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tickets (number, text, keywords, owner_id) VALUES (?, ?, ?, ?)",
        (number, text, keywords, owner_id)
    )
    conn.commit()
    conn.close()
    return number

def get_random_ticket(owner_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, number, text, keywords FROM tickets WHERE owner_id = ? ORDER BY RANDOM() LIMIT 1",
        (owner_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "number": row[1], "text": row[2], "keywords": row[3]}
    return None

def get_ticket_count(owner_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE owner_id = ?", (owner_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def save_result(user_id: int, ticket_id: int, score: int, max_score: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO results (user_id, ticket_id, score, max_score) VALUES (?, ?, ?, ?)",
        (user_id, ticket_id, score, max_score)
    )
    conn.commit()
    conn.close()

def get_user_stats(user_id: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT t.number, r.score, r.max_score, r.created_at
        FROM results r JOIN tickets t ON r.ticket_id = t.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC LIMIT 10
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def clear_tickets(owner_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM tickets WHERE owner_id = ?", (owner_id,))
    try:
        cur.execute("DELETE FROM sqlite_sequence WHERE name='tickets'")
    except Exception:
        pass
    conn.commit()
    conn.close()

def clear_user_results(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM results WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()