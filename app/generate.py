"""
Qwen3-TTS - Gerador de áudio para narração (CLI)
Suporta modelos 0.6B (rápido) e 1.7B (qualidade)
Transcrição automática via Whisper
"""

import argparse
import json
import os
import re
import time

import numpy as np
import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

# Otimizações CUDA
torch.backends.cudnn.benchmark = True
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

BASE_DIR = os.path.dirname(__file__)
MODELS_DIR = os.path.join(BASE_DIR, "models")
REF_DIR = os.path.join(BASE_DIR, "reference_audio")
TRANSCRIPTIONS_FILE = os.path.join(REF_DIR, "transcriptions.json")

MODEL_PATHS = {
    "0.6B": os.path.join(MODELS_DIR, "0.6B"),
    "1.7B": os.path.join(MODELS_DIR, "1.7B"),
}


def get_transcription(voice: str):
    """Busca transcrição salva ou transcreve com Whisper."""
    transcriptions = {}
    if os.path.exists(TRANSCRIPTIONS_FILE):
        with open(TRANSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
            transcriptions = json.load(f)

    filename = f"{voice}.wav"
    if filename in transcriptions:
        return transcriptions[filename]

    # Transcrever com Whisper
    import whisper
    print(f"Transcrevendo {filename} com Whisper...")
    model = whisper.load_model("medium", device="cuda")
    result = model.transcribe(os.path.join(REF_DIR, filename), language="pt")
    text = result["text"].strip()

    transcriptions[filename] = text
    with open(TRANSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transcriptions, f, ensure_ascii=False, indent=2)

    del model
    torch.cuda.empty_cache()
    print(f"Transcrição: {text[:80]}...")
    return text


def load_model(size: str):
    path = MODEL_PATHS[size]
    print(f"Carregando modelo {size}...")
    model = Qwen3TTSModel.from_pretrained(
        path,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )

    # torch.compile no talker (primeira execução mais lenta, depois ~6x mais rápido)
    print(f"Compilando talker {size}...")
    model.model.talker = torch.compile(model.model.talker, mode="reduce-overhead")

    print(f"Modelo {size} pronto!")
    return model


def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS - Gerador de narração")
    parser.add_argument(
        "--model", "-m",
        choices=["0.6B", "1.7B"],
        default="1.7B",
        help="Tamanho do modelo (padrão: 1.7B)",
    )
    parser.add_argument(
        "--text", "-t",
        help="Texto para converter em áudio",
    )
    parser.add_argument(
        "--text-file", "-f",
        help="Arquivo .txt com o texto (alternativa ao --text)",
    )
    parser.add_argument(
        "--voice", "-v",
        default="homem",
        help="Nome da voz: homem, mulher, etc. (padrão: homem)",
    )
    parser.add_argument(
        "--language", "-l",
        default="Portuguese",
        help="Idioma do texto (padrão: Portuguese)",
    )
    parser.add_argument(
        "--output", "-o",
        default="output/output.wav",
        help="Caminho do arquivo de saída (padrão: output/output.wav)",
    )

    args = parser.parse_args()

    # Texto obrigatório por argumento ou arquivo
    text = args.text
    if args.text_file:
        with open(args.text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()

    if not text:
        parser.error("Use --text ou --text-file para fornecer o texto.")

    ref_audio = os.path.join(REF_DIR, f"{args.voice}.wav")
    if not os.path.exists(ref_audio):
        parser.error(f"Voz '{args.voice}' não encontrada em {REF_DIR}")

    ref_text = get_transcription(args.voice)
    model = load_model(args.model)

    # Prompt cacheado com clone completo
    cached_prompt = model.create_voice_clone_prompt(
        ref_audio=ref_audio,
        ref_text=ref_text,
    )

    # Divide em chunks de ~100 chars
    sentences = re.split(r'(?<=[.!?;:])\s+', text.strip())
    chunks, current = [], ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > 100:
            chunks.append(current.strip())
            current = s
        else:
            current = f"{current} {s}".strip() if current else s
    if current:
        chunks.append(current.strip())

    print(f"Gerando áudio ({len(text)} caracteres, {len(chunks)} chunks)...")
    start = time.time()

    audio_parts = []
    sr = None
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}/{len(chunks)}: {len(chunk)} chars")
        with torch.inference_mode():
            wavs, sr = model.generate_voice_clone(
                text=chunk,
                language=args.language,
                voice_clone_prompt=cached_prompt,
                non_streaming_mode=True,
                max_new_tokens=2048,
                temperature=0.7,
                top_k=30,
                repetition_penalty=1.05,
            )
        audio_parts.append(wavs[0])

    # Concatena com pausa de 300ms
    if len(audio_parts) > 1:
        pause = np.zeros(int(sr * 0.3), dtype=audio_parts[0].dtype)
        combined = []
        for i, part in enumerate(audio_parts):
            combined.append(part)
            if i < len(audio_parts) - 1:
                combined.append(pause)
        final_wav = np.concatenate(combined)
    else:
        final_wav = audio_parts[0]

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    sf.write(args.output, final_wav, sr)

    elapsed = time.time() - start
    print(f"Áudio salvo em: {args.output}")
    print(f"Tempo de geração: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
