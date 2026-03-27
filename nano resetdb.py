import os
import sqlite3

DB_FILE = "tondomaingame.db"

# удалить старую базу
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
    print("Old database deleted")

# создать новую
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# таблица пользователей
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    balance INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# таблица транзакций
cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()
conn.close()

print("New empty database created")
