import argparse
import os
import sys

from huggingface_hub import snapshot_download


MODEL_REPOS = {
    "0.6B": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
    "1.7B": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
}


def download_model(model_size: str, models_dir: str) -> None:
    repo_id = MODEL_REPOS[model_size]
    target_dir = os.path.join(models_dir, model_size)
    os.makedirs(models_dir, exist_ok=True)

    print(f"Downloading {model_size} model from {repo_id}...")
    print(f"Target folder: {target_dir}")

    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
    )

    print(f"[OK] Model {model_size} downloaded successfully.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Evo Qwen3TTS models from Hugging Face.")
    parser.add_argument("--model", choices=["0.6B", "1.7B", "all"], required=True)
    parser.add_argument("--models-dir", required=True)
    args = parser.parse_args()

    try:
        if args.model == "all":
            for size in ("0.6B", "1.7B"):
                download_model(size, args.models_dir)
        else:
            download_model(args.model, args.models_dir)
    except KeyboardInterrupt:
        print("\n[ERROR] Download canceled by user.")
        return 1
    except Exception as exc:
        print(f"[ERROR] Failed to download model(s): {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
