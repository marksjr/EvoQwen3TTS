"""
Qwen3-TTS API - Servidor local para geração de áudio
Roda em http://localhost:5050
Transcrição automática dos áudios de referência via Whisper
"""

import json
import os
import re
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager

import numpy as np
import torch
import soundfile as sf
import whisper

# Otimizações CUDA
torch.backends.cudnn.benchmark = True
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(APP_DIR)
MODELS_DIR = os.path.join(PROJECT_DIR, "models")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
REF_DIR = os.path.join(PROJECT_DIR, "reference_audio")
TRANSCRIPTIONS_FILE = os.path.join(REF_DIR, "transcriptions.json")
INDEX_HTML = os.path.join(APP_DIR, "index.html")
DOCS_HTML = os.path.join(APP_DIR, "docs.html")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Cache
loaded_models = {}
voice_clone_prompts = {}
transcriptions = {}
transcription_lock = threading.Lock()
SYSTEM_VOICE_PREFIXES = {
    "Arabic",
    "Danish",
    "Dutch",
    "English",
    "French",
    "German",
    "Japanese",
    "Norwegian",
    "Portuguese",
    "Portuguese_Brazilian",
    "Spanish",
    "Swedish",
}
startup_status = {
    "phase": "idle",
    "is_transcribing": False,
    "total_voices": 0,
    "transcribed_voices": 0,
    "pending_voices": 0,
    "current_voice": None,
    "last_error": None,
}


def load_transcriptions():
    global transcriptions
    if os.path.exists(TRANSCRIPTIONS_FILE):
        with open(TRANSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            transcriptions = json.load(f)


def save_transcriptions():
    with open(TRANSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transcriptions, f, ensure_ascii=False, indent=2)


def update_startup_status(**kwargs):
    with transcription_lock:
        startup_status.update(kwargs)


def get_voice_files():
    """Retorna todos os .wav do diretório de referência."""
    return [f for f in os.listdir(REF_DIR) if f.lower().endswith(".wav")]


def is_protected_system_voice(name: str) -> bool:
    return any(name.startswith(f"{prefix}_") for prefix in SYSTEM_VOICE_PREFIXES)


def transcribe_references():
    load_transcriptions()
    wav_files = get_voice_files()
    needs = [f for f in wav_files if f not in transcriptions]
    update_startup_status(
        phase="transcribing",
        is_transcribing=bool(needs),
        total_voices=len(wav_files),
        transcribed_voices=len(wav_files) - len(needs),
        pending_voices=len(needs),
        current_voice=None,
        last_error=None,
    )

    if not needs:
        print("Transcriptions already exist for all reference audios.")
        update_startup_status(phase="ready", is_transcribing=False)
        return

    print(f"Transcribing {len(needs)} audio file(s) with Whisper...")
    whisper_model = None

    try:
        whisper_model = whisper.load_model("medium", device="cuda")

        for index, f in enumerate(needs, start=1):
            path = os.path.join(REF_DIR, f)
            update_startup_status(current_voice=f)
            print(f"  Transcribing: {f}...")
            result = whisper_model.transcribe(path, language=None)
            transcriptions[f] = result["text"].strip()
            save_transcriptions()
            update_startup_status(
                transcribed_voices=len(wav_files) - (len(needs) - index),
                pending_voices=len(needs) - index,
            )
            print(f"  -> {transcriptions[f][:80]}...")
    except Exception as exc:
        update_startup_status(phase="error", is_transcribing=False, last_error=str(exc))
        raise
    finally:
        if whisper_model is not None:
            del whisper_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    update_startup_status(phase="ready", is_transcribing=False, current_voice=None)
    print("Transcriptions completed.")


def get_model(size: str):
    if size not in loaded_models:
        # Limpa modelo anterior e prompts cacheados
        for key in list(loaded_models.keys()):
            del loaded_models[key]
        voice_clone_prompts.clear()
        torch.cuda.empty_cache()

        path = os.path.join(MODELS_DIR, size)
        print(f"Carregando modelo TTS {size}...")
        model = Qwen3TTSModel.from_pretrained(
            path,
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

        # torch.compile no talker (parte mais lenta da geração)
        print(f"Compilando talker {size} (primeira geração será mais lenta)...")
        model.model.talker = torch.compile(model.model.talker, mode="reduce-overhead")

        loaded_models[size] = model
        print(f"Modelo {size} pronto!")

        # Pré-cachear prompts de todas as vozes
        cache_voice_prompts(model)

    return loaded_models[size]


def cache_voice_prompts(model):
    """Pré-processa áudios de referência para evitar re-encoding a cada request."""
    for f in get_voice_files():
        voice_name = f.rsplit(".", 1)[0]
        if voice_name in voice_clone_prompts:
            continue
        ref_audio = os.path.join(REF_DIR, f)
        ref_text = transcriptions.get(f, "")
        if not ref_text:
            continue

        print(f"  Cacheando prompt de voz: {voice_name}...")
        prompt = model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        voice_clone_prompts[voice_name] = prompt
        print(f"  -> {voice_name} cacheado!")


def run_startup_transcription():
    try:
        transcribe_references()
    except Exception as exc:
        print(f"Startup transcription failed: {exc}")


@asynccontextmanager
async def lifespan(app):
    load_transcriptions()
    wav_files = get_voice_files()
    update_startup_status(
        phase="starting",
        is_transcribing=False,
        total_voices=len(wav_files),
        transcribed_voices=len([f for f in wav_files if f in transcriptions]),
        pending_voices=len([f for f in wav_files if f not in transcriptions]),
        current_voice=None,
        last_error=None,
    )
    thread = threading.Thread(target=run_startup_transcription, daemon=True)
    thread.start()
    yield


app = FastAPI(
    title="Evo Qwen3TTS API",
    summary="Local API for text-to-speech generation, voice cloning, and voice library management.",
    description=(
        "This API powers Evo Qwen3TTS. A request combines text, a model, a reference voice, a text language, and an "
        "optional emotion preset. The reference voice defines the speaker timbre. The language defines how the input "
        "text should be pronounced and may be different from the reference voice language."
    ),
    version="1.0.0",
    docs_url="/api-docs",
    redoc_url="/api-redoc",
    openapi_tags=[
        {"name": "generation", "description": "Speech generation endpoints."},
        {"name": "voices", "description": "Reference voice management endpoints."},
        {"name": "ui", "description": "Web interface and generated audio files."},
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., description="The text content that will be synthesized into speech.")
    model: str = Field("1.7B", description="Model folder to use. Supported values: 0.6B or 1.7B.")
    voice: str = Field(
        "Portuguese_Brazilian_Female_Speaker_01",
        description="Reference voice name without the .wav extension. This controls the speaker timbre, not the text language.",
    )
    language: str = Field(
        "portuguese",
        description="Language of the input text for pronunciation. This may be different from the reference voice language.",
    )
    emotion: str = Field("neutral", description="Optional speaking style or emotion preset.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "Ola, esta e uma demonstracao do Evo Qwen3TTS.",
                    "model": "1.7B",
                    "voice": "Portuguese_Brazilian_Female_Speaker_01",
                    "language": "portuguese",
                    "emotion": "neutral",
                },
                {
                    "text": "Hello, this is an English demo using the selected speaker timbre.",
                    "model": "1.7B",
                    "voice": "English_Female_Speaker_01",
                    "language": "english",
                    "emotion": "confident",
                },
            ]
        }
    }


class GenerateResponse(BaseModel):
    success: bool
    file: str
    url: str
    duration: float
    generation_time: float
    characters: int
    chunks: int
    model: str
    voice: str
    emotion: str


class VoiceInfo(BaseModel):
    name: str
    duration: float
    transcription: str


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class UploadVoiceResponse(BaseModel):
    success: bool
    name: str
    duration: float
    transcription: str


class DeleteVoiceResponse(BaseModel):
    success: bool
    deleted: str


class SystemStatusResponse(BaseModel):
    phase: str
    is_transcribing: bool
    total_voices: int
    transcribed_voices: int
    pending_voices: int
    current_voice: str | None
    available_voices: int
    ready_voices: int
    last_error: str | None


EMOTION_PROMPTS = {
    "neutral": "",
    "happy": (
        "<emotion>happiness</emotion> "
        "Speak with a bright, joyful tone. Your voice should radiate warmth and enthusiasm, "
        "with a slightly higher pitch and upbeat rhythm. Smile through your words, "
        "letting genuine happiness and positive energy flow naturally in every syllable."
    ),
    "sad": (
        "<emotion>sadness</emotion> "
        "Speak with a deep, sorrowful tone. Your voice should carry the weight of melancholy, "
        "with a slower pace, lower pitch, and gentle pauses between phrases. "
        "Let each word convey a sense of loss, longing, and quiet grief."
    ),
    "angry": (
        "<emotion>anger</emotion> "
        "Speak with intense, forceful energy. Your voice should be sharp and commanding, "
        "with a faster pace and emphatic stress on key words. "
        "Channel raw frustration and indignation, letting controlled fury resonate through every phrase."
    ),
    "fearful": (
        "<emotion>fear</emotion> "
        "Speak with a trembling, anxious voice. Your tone should convey vulnerability and dread, "
        "with a slightly higher pitch, uneven rhythm, and hesitant pauses. "
        "Let your words carry the tension of someone facing the unknown, breathless and uneasy."
    ),
    "surprised": (
        "<emotion>surprise</emotion> "
        "Speak with sudden, wide-eyed astonishment. Your voice should jump in pitch and energy, "
        "with quick bursts of expression and dramatic pauses. "
        "Convey genuine shock and wonder, as if discovering something truly unexpected."
    ),
    "disgusted": (
        "<emotion>disgust</emotion> "
        "Speak with a tone of revulsion and displeasure. Your voice should carry a slight nasal quality, "
        "with drawn-out vowels on unpleasant words and a slower, deliberate pace. "
        "Express visceral repulsion and deep disapproval in every utterance."
    ),
    "excited": (
        "<emotion>excitement</emotion> "
        "Speak with explosive, infectious enthusiasm. Your voice should be high-energy and fast-paced, "
        "with rising intonation and dynamic volume changes. "
        "Radiate pure exhilaration and passionate eagerness, barely containing your excitement."
    ),
    "tender": (
        "<emotion>tenderness</emotion> "
        "Speak with a soft, warm, and loving tone. Your voice should be gentle and intimate, "
        "with a lower volume and smooth, flowing rhythm. "
        "Let every word feel like a caring embrace, full of affection, sweetness, and deep emotional connection."
    ),
    "sarcastic": (
        "<emotion>sarcasm</emotion> "
        "Speak with a dry, ironic tone dripping with subtle mockery. Your voice should have exaggerated "
        "emphasis on certain words, deliberate pauses for effect, and a slightly flat delivery. "
        "Convey that you mean the exact opposite of what you're saying, with a knowing smirk in your voice."
    ),
    "whisper": (
        "<emotion>whisper</emotion> "
        "Speak in a hushed, breathy whisper. Your voice should be barely audible, intimate and secretive, "
        "with soft consonants and airy vowels. "
        "Create a sense of closeness and confidentiality, as if sharing a precious secret."
    ),
    "dramatic": (
        "<emotion>drama</emotion> "
        "Speak with theatrical, larger-than-life intensity. Your voice should command attention with "
        "sweeping dynamic range, from powerful crescendos to haunting pianissimos. "
        "Deliver every line as if performing on a grand stage, with gravitas and emotional depth."
    ),
    "calm": (
        "<emotion>calm</emotion> "
        "Speak with a serene, measured, and tranquil tone. Your voice should flow like a gentle stream, "
        "with a steady pace, even breathing, and soothing low pitch. "
        "Radiate inner peace and composure, creating a meditative and reassuring atmosphere."
    ),
    "anxious": (
        "<emotion>anxiety</emotion> "
        "Speak with a restless, worried tone. Your voice should have a slightly faster pace with "
        "irregular rhythm, subtle vocal tension, and occasional rushed phrases. "
        "Convey the inner turmoil of overthinking, with nervous energy seeping through every word."
    ),
    "confident": (
        "<emotion>confidence</emotion> "
        "Speak with a strong, assured, and authoritative tone. Your voice should project certainty and power, "
        "with a steady pace, firm articulation, and resonant depth. "
        "Command the room with unwavering self-assurance and charismatic conviction."
    ),
    "melancholic": (
        "<emotion>melancholy</emotion> "
        "Speak with a wistful, bittersweet tone full of nostalgia. Your voice should drift slowly, "
        "with gentle sighs between phrases, a soft wavering quality, and reflective pauses. "
        "Evoke the beauty of cherished memories tinged with the ache of things lost to time."
    ),
    "hopeful": (
        "<emotion>hope</emotion> "
        "Speak with a warm, uplifting tone that builds gradually. Your voice should start gentle and grow "
        "with quiet determination, carrying an undercurrent of optimism and resilience. "
        "Let each phrase kindle a spark of belief that something better lies ahead."
    ),
    "seductive": (
        "<emotion>seduction</emotion> "
        "Speak with a low, velvety, and alluring tone. Your voice should be smooth and magnetic, "
        "with a slow, deliberate pace and lingering emphasis on sensual words. "
        "Create an intimate atmosphere of mystery and irresistible charm."
    ),
    "storytelling": (
        "<emotion>narration</emotion> "
        "Speak as a masterful storyteller captivating an audience. Your voice should have rich dynamics, "
        "shifting between tension and release, with vivid characterization and well-timed pauses. "
        "Paint scenes with your voice, drawing listeners deep into the narrative with immersive expression."
    ),
    "news": (
        "<emotion>formal</emotion> "
        "Speak with a professional, clear, and authoritative broadcast tone. Your voice should be crisp, "
        "well-articulated, and neutral with measured pacing. "
        "Deliver information with journalistic precision, gravitas, and polished presentation."
    ),
}


def split_text_chunks(text: str, max_chars: int = 200) -> list[str]:
    """Divide texto em chunks por frases, respeitando limite de caracteres."""
    # Divide por pontuação final (.!?;:) mantendo o delimitador
    sentences = re.split(r'(?<=[.!?;:])\s+', text.strip())

    chunks = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence

    if current:
        chunks.append(current.strip())

    return chunks


def generate_chunk(model, text, language, cached_prompt, ref_audio, ref_text, emotion_prompt=""):
    """Gera áudio para um chunk de texto, com emoção via instruct separado."""
    gen_kwargs = {
        "non_streaming_mode": True,
        "max_new_tokens": 2048,
        "temperature": 0.7,
        "top_k": 30,
        "repetition_penalty": 1.05,
    }

    with torch.inference_mode():
        if emotion_prompt:
            # Passa emoção como instruct_ids separado (não concatenado ao texto)
            # Isso evita que o prompt de emoção seja falado junto com o texto
            input_texts = [model._build_assistant_text(text)]
            input_ids = model._tokenize_texts(input_texts)

            instruct_text = model._build_instruct_text(emotion_prompt)
            instruct_ids = [model._tokenize_texts([instruct_text])[0]]

            # Prepara voice_clone_prompt
            if cached_prompt:
                if isinstance(cached_prompt, list):
                    prompt_items = cached_prompt
                else:
                    prompt_items = [cached_prompt] if not isinstance(cached_prompt, dict) else None

                if prompt_items is not None:
                    voice_clone_prompt_dict = model._prompt_items_to_voice_clone_prompt(prompt_items)
                    ref_texts_for_ids = [it.ref_text for it in prompt_items]
                else:
                    voice_clone_prompt_dict = cached_prompt
                    ref_texts_for_ids = None
            else:
                prompt_items = model.create_voice_clone_prompt(
                    ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False
                )
                voice_clone_prompt_dict = model._prompt_items_to_voice_clone_prompt(prompt_items)
                ref_texts_for_ids = [it.ref_text for it in prompt_items]

            ref_ids = None
            if ref_texts_for_ids is not None:
                ref_ids = []
                for rt in ref_texts_for_ids:
                    if rt is None or rt == "":
                        ref_ids.append(None)
                    else:
                        ref_tok = model._tokenize_texts([model._build_ref_text(rt)])[0]
                        ref_ids.append(ref_tok)

            merged_kwargs = model._merge_generate_kwargs(**gen_kwargs)

            talker_codes_list, _ = model.model.generate(
                input_ids=input_ids,
                instruct_ids=instruct_ids,
                ref_ids=ref_ids,
                voice_clone_prompt=voice_clone_prompt_dict,
                languages=[language],
                **merged_kwargs,
            )

            # Decodifica removendo o áudio de referência
            codes_for_decode = []
            for i, codes in enumerate(talker_codes_list):
                ref_code_list = voice_clone_prompt_dict.get("ref_code", None)
                if ref_code_list is not None and ref_code_list[i] is not None:
                    codes_for_decode.append(torch.cat([ref_code_list[i].to(codes.device), codes], dim=0))
                else:
                    codes_for_decode.append(codes)

            wavs_all, sr = model.model.speech_tokenizer.decode([{"audio_codes": c} for c in codes_for_decode])

            wavs_out = []
            for i, wav in enumerate(wavs_all):
                ref_code_list = voice_clone_prompt_dict.get("ref_code", None)
                if ref_code_list is not None and ref_code_list[i] is not None:
                    ref_len = int(ref_code_list[i].shape[0])
                    total_len = int(codes_for_decode[i].shape[0])
                    cut = int(ref_len / max(total_len, 1) * wav.shape[0])
                    wavs_out.append(wav[cut:])
                else:
                    wavs_out.append(wav)

            return wavs_out[0], sr
        else:
            if cached_prompt:
                wavs, sr = model.generate_voice_clone(
                    text=text,
                    language=language,
                    voice_clone_prompt=cached_prompt,
                    **gen_kwargs,
                )
            else:
                wavs, sr = model.generate_voice_clone(
                    text=text,
                    language=language,
                    ref_audio=ref_audio,
                    ref_text=ref_text,
                    **gen_kwargs,
                )

            return wavs[0], sr


@app.post(
    "/generate",
    tags=["generation"],
    summary="Generate speech audio",
    description=(
        "Generates a `.wav` file from text. `voice` selects the speaker timbre. `language` selects the language of the "
        "input text for pronunciation. They do not need to match. Example: an English text can be spoken with a "
        "Brazilian Portuguese reference voice if that is the voice style you want."
    ),
    response_model=GenerateResponse,
)
def generate(req: TTSRequest):
    if req.model not in ("0.6B", "1.7B"):
        raise HTTPException(400, "Modelo deve ser 0.6B ou 1.7B")

    ref_file = f"{req.voice}.wav"
    ref_audio = os.path.join(REF_DIR, ref_file)
    if not os.path.exists(ref_audio):
        raise HTTPException(400, f"Voz '{req.voice}' não encontrada")

    ref_text = transcriptions.get(ref_file)
    if not ref_text:
        raise HTTPException(400, f"Transcrição não encontrada para '{req.voice}'.")

    model = get_model(req.model)
    cached_prompt = voice_clone_prompts.get(req.voice)

    # Obtém prompt de emoção (será passado separadamente como instruct)
    emotion_prompt = EMOTION_PROMPTS.get(req.emotion, "")

    start = time.time()

    # Divide texto longo em chunks de ~100 chars para máxima velocidade
    chunks = split_text_chunks(req.text, max_chars=100)
    print(f"Gerando {len(chunks)} chunk(s) para {len(req.text)} caracteres...")

    audio_parts = []
    sr = None
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}/{len(chunks)}: {len(chunk)} chars")
        wav, sr = generate_chunk(model, chunk, req.language, cached_prompt, ref_audio, ref_text, emotion_prompt)
        audio_parts.append(wav)

    # Concatena chunks com pequena pausa entre eles
    if len(audio_parts) > 1:
        pause = np.zeros(int(sr * 0.3), dtype=audio_parts[0].dtype)  # 300ms de pausa
        combined = []
        for i, part in enumerate(audio_parts):
            combined.append(part)
            if i < len(audio_parts) - 1:
                combined.append(pause)
        final_wav = np.concatenate(combined)
    else:
        final_wav = audio_parts[0]

    elapsed = time.time() - start

    filename = f"{uuid.uuid4().hex}.wav"
    filepath = os.path.join(OUTPUT_DIR, filename)
    sf.write(filepath, final_wav, sr)

    return {
        "success": True,
        "file": filename,
        "url": f"/output/{filename}",
        "duration": round(len(final_wav) / sr, 2),
        "generation_time": round(elapsed, 2),
        "characters": len(req.text),
        "chunks": len(chunks),
        "model": req.model,
        "voice": req.voice,
        "emotion": req.emotion,
    }


@app.get(
    "/voices",
    tags=["voices"],
    summary="List available voices",
    description="Returns every `.wav` reference voice found in `reference_audio` with duration and stored transcription.",
    response_model=VoicesResponse,
)
def list_voices():
    voices = []
    for f in get_voice_files():
        name = f.rsplit(".", 1)[0]
        data, sr = sf.read(os.path.join(REF_DIR, f))
        voices.append({
            "name": name,
            "duration": round(len(data) / sr, 1),
            "transcription": transcriptions.get(f, ""),
        })
    voices.sort(key=lambda v: v["name"])
    return {"voices": voices}


@app.get(
    "/system-status",
    tags=["ui"],
    summary="Get startup and transcription status",
    description="Returns API startup status and background transcription progress for the web interface.",
    response_model=SystemStatusResponse,
)
def get_system_status():
    wav_files = get_voice_files()
    ready_voices = sum(1 for f in wav_files if transcriptions.get(f))
    with transcription_lock:
        status = dict(startup_status)
    status["available_voices"] = len(wav_files)
    status["ready_voices"] = ready_voices
    return status


@app.post(
    "/upload-voice",
    tags=["voices"],
    summary="Upload a new reference voice",
    description=(
        "Uploads a `.wav` file to the local voice library, transcribes it with Whisper, and caches the prompt "
        "for any model that is already loaded."
    ),
    response_model=UploadVoiceResponse,
)
async def upload_voice(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".wav"):
        raise HTTPException(400, "Apenas arquivos .wav são aceitos")

    safe_name = re.sub(r'[^\w\-.]', '_', file.filename)
    dest = os.path.join(REF_DIR, safe_name)

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Transcrever com Whisper
    print(f"Transcrevendo novo áudio: {safe_name}...")
    whisper_model = whisper.load_model("medium", device="cuda")
    result = whisper_model.transcribe(dest, language=None)
    transcriptions[safe_name] = result["text"].strip()
    save_transcriptions()
    del whisper_model
    torch.cuda.empty_cache()
    print(f"  -> {transcriptions[safe_name][:80]}...")

    # Cachear prompt se modelo já estiver carregado
    for model in loaded_models.values():
        voice_name = safe_name.rsplit(".", 1)[0]
        prompt = model.create_voice_clone_prompt(
            ref_audio=dest,
            ref_text=transcriptions[safe_name],
        )
        voice_clone_prompts[voice_name] = prompt

    data, sr = sf.read(dest)
    return {
        "success": True,
        "name": safe_name.rsplit(".", 1)[0],
        "duration": round(len(data) / sr, 1),
        "transcription": transcriptions[safe_name],
    }


@app.delete(
    "/voices/{name}",
    tags=["voices"],
    summary="Delete a reference voice",
    description="Removes a voice file, its cached transcription, and any cached prompt using the provided voice name.",
    response_model=DeleteVoiceResponse,
)
def delete_voice(name: str):
    filename = f"{name}.wav"
    filepath = os.path.join(REF_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"Voz '{name}' não encontrada")

    if is_protected_system_voice(name):
        raise HTTPException(403, "System voices are protected and cannot be deleted.")

    os.remove(filepath)
    transcriptions.pop(filename, None)
    save_transcriptions()
    voice_clone_prompts.pop(name, None)
    return {"success": True, "deleted": name}


app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


@app.get("/", tags=["ui"], summary="Open the web interface", include_in_schema=False)
def serve_index():
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.get("/docs.html", tags=["ui"], summary="Open the system documentation", include_in_schema=False)
def serve_docs_html():
    return FileResponse(DOCS_HTML, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5050)



