# Evo Qwen3TTS

Evo Qwen3TTS is a local FastAPI application for text-to-speech generation, voice cloning, automatic Whisper transcription, and browser-based voice management.

## Main URLs

- App UI: `http://localhost:5050`
- System docs: `http://localhost:5050/docs.html`
- Swagger: `http://localhost:5050/api-docs`
- ReDoc: `http://localhost:5050/api-redoc`

## Notes

- automatic model download from the installer requires internet access
- if model download fails, you can place `0.6B` and/or `1.7B` manually into the root `models\` folder
- the repository root now includes an MIT `LICENSE`

## Important Rule

- `voice` selects the speaker timbre
- `language` selects the language of the text you typed
- they can be different, but matching them is usually clearer and more natural

## Recommended Generate Examples

Portuguese text with Portuguese voice:

```json
{
  "text": "Ola, esta e uma demonstracao do Evo Qwen3TTS.",
  "model": "1.7B",
  "voice": "Portuguese_Brazilian_Female_Speaker_01",
  "language": "portuguese",
  "emotion": "neutral"
}
```

English text with English voice:

```json
{
  "text": "Hello, this is an English demo for Evo Qwen3TTS.",
  "model": "1.7B",
  "voice": "English_Female_Speaker_01",
  "language": "english",
  "emotion": "confident"
}
```

## Folder Layout

- `api.py`: backend API
- `index.html`: main interface
- `docs.html`: HTML documentation
- `README.md`: project notes
- `generate.py`: helper script
- `requirements.txt`: dependency list
- `..\start.bat`: launcher
- `..\install.bat`: installer
