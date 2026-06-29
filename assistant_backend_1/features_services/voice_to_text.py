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
            local_file_path,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=200,
                threshold=0.3,
            ),
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            word_timestamps=False,
        )

        transcript = "".join([segment.text for segment in segments]).strip()

        # If still empty after transcription — audio too short or silence
        if not transcript:
            print("⚠️ Transcript empty — audio may be too short or silent")
            return "I couldn't catch that — could you say it again or send a longer message?"

        print("this is transcript", transcript)
        return transcript

    except Exception as e:
        print(f"Error: {e}")
        return "Error transcribing."
