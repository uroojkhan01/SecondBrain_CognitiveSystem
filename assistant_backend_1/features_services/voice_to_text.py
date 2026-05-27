import os
from faster_whisper import WhisperModel

MODEL_SIZE = "tiny"
model = WhisperModel(
    MODEL_SIZE,
    device="cpu",
    compute_type="int8",
    cpu_threads=1,
    num_workers=1
)


def transcribe_audio_file(local_file_path: str) -> str:
    if not os.path.exists(local_file_path):
        return "Audio file missing."

    try:
        print("now in transcribe audio")
        segments, info = model.transcribe(
            local_file_path, beam_size=1)  # beam_size=1 is faster
        transcript = "".join([segment.text for segment in segments]).strip()
        print("this is trancript", transcript)
        return transcript
    except Exception as e:
        print(f"Error: {e}")
        return "Error transcribing."
