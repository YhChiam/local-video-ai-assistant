import os
import subprocess
import traceback

# Ensure ffmpeg from repo is first on PATH for this process
ffmpeg_bin = r"C:\yhchiam\local-video-ai-assistant\backend\ffmpeg\bin"
os.environ['PATH'] = ffmpeg_bin + os.pathsep + os.environ.get('PATH', '')

wav = r"C:\temp\tts.wav"
mp4 = r"C:\temp\test.mp4"

# 1) Synthesize short TTS WAV using pyttsx3
try:
    import pyttsx3
    tts = pyttsx3.init()
    tts.save_to_file('Hello world. This is a local transcription test.', wav)
    tts.runAndWait()
    print('TTS saved to', wav)
except Exception as e:
    print('TTS synthesis failed:', e)
    traceback.print_exc()

# 2) Package into MP4 using ffmpeg (AAC)
try:
    if os.path.exists(wav):
        cmd = [os.path.join(ffmpeg_bin, 'ffmpeg.exe'), '-y', '-i', wav, '-c:a', 'aac', '-b:a', '64k', mp4]
        subprocess.check_call(cmd)
        print('Created MP4 at', mp4)
    else:
        print('WAV not found; skipping mp4 creation')
except Exception as e:
    print('ffmpeg packaging failed:', e)
    traceback.print_exc()

# 3) Transcribe with whisper tiny (fast)
try:
    import whisper
    print('Loading whisper tiny model (may download weights)...')
    model = whisper.load_model('tiny')
    print('Model loaded, running transcription...')
    result = model.transcribe(mp4 if os.path.exists(mp4) else wav)
    print('TRANSCRIPTION RESULT:')
    print(result.get('text'))
except Exception as e:
    print('Whisper transcription failed:', e)
    traceback.print_exc()
