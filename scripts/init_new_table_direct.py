
import sqlite3
from pathlib import Path

DB_PATH = Path("data/gemini_chat/contexts.db")

def main():
    print(f"Connecting to {DB_PATH}")
    if not DB_PATH.exists():
        print("Database not found, skipping (will be created on bot start).")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Creating message_archive table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            message_id TEXT,
            timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    print("Creating index...")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_archive_key_time ON message_archive(context_key, timestamp)
    """)
    
    conn.commit()
    conn.close()
    print("Done!")

if __name__ == "__main__":
    main()
