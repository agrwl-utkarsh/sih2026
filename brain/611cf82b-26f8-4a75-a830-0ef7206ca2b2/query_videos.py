import sqlite3
conn = sqlite3.connect('captions.db')
cursor = conn.cursor()
cursor.execute("SELECT id, status, error_message FROM videos WHERE id = '98385e59-af99-420c-a5dd-216ef0ce8af3'")
video = cursor.fetchone()
print(f"Video Status: {video}")

cursor.execute("SELECT COUNT(id) FROM segments WHERE video_id = '98385e59-af99-420c-a5dd-216ef0ce8af3'")
segments_count = cursor.fetchone()[0]
print(f"Segments Count: {segments_count}")
conn.close()
