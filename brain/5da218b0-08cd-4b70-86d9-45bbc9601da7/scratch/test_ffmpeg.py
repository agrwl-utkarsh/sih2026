import sqlite3
import subprocess
import os
import datetime

video_id = '673a4ba2-7256-43f3-83a5-9f368e602452'
UPLOAD_FOLDER = r'c:\Users\uagar\ai-captioner\backend\uploads'
OUTPUT_FOLDER = r'c:\Users\uagar\ai-captioner\backend\outputs'

video_path = os.path.join(UPLOAD_FOLDER, f'{video_id}.mp4')
srt_path = os.path.join(UPLOAD_FOLDER, f'{video_id}_temp.srt')
out_path = os.path.join(OUTPUT_FOLDER, f'captioned_{video_id}.mp4')

conn = sqlite3.connect(r'c:\Users\uagar\ai-captioner\backend\captions.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT * FROM segments WHERE video_id = ? ORDER BY display_order ASC', (video_id,)).fetchall()
conn.close()

def format_timestamp_srt(seconds):
    td = datetime.timedelta(seconds=seconds)
    ts = int(td.total_seconds())
    ms = int(td.microseconds / 1000)
    return f'{ts//3600:02d}:{(ts%3600)//60:02d}:{ts%60:02d},{ms:03d}'

srt_content = ''
for i, r in enumerate(rows):
    srt_content += f"{i+1}\n{format_timestamp_srt(r['start_time'])} --> {format_timestamp_srt(r['end_time'])}\n{r['text']}\n\n"

with open(srt_path, 'w', encoding='utf-8') as f:
    f.write(srt_content)

style_str = 'Fontname=Arial,FontSize=24,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BackColour=&H00000000,BorderStyle=1,Outline=1.5,Shadow=1,Alignment=2,Bold=1,Italic=0'
safe_srt = srt_path.replace('\\', '/').replace(':', '\\:')
cmd = ['ffmpeg', '-y', '-i', video_path, '-vf', f"subtitles='{safe_srt}':force_style='{style_str}'", '-c:a', 'copy', out_path]

print('Running:', ' '.join(cmd))
res = subprocess.run(cmd, capture_output=True, text=True)
print('STDOUT:', res.stdout)
print('STDERR:', res.stderr)
print('EXIT CODE:', res.returncode)
