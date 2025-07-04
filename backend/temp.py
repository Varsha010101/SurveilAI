import sqlite3

conn = sqlite3.connect("threat_history.db")
cursor = conn.cursor()

# Check if the threats table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='threats'")
table_exists = cursor.fetchone()

if table_exists:
    print("✅ 'threats' table exists.")
else:
    print("❌ 'threats' table not found. Check DB setup.")
    
conn.close()
