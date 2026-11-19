# Original chat client

This is the first version of the project: a multi-provider chat app (Ollama, OpenAI, Anthropic, HuggingFace and
any OpenAI-compatible endpoint) with a web interface, voice input and a keyword-triggered memory. It is kept as a
reference. The memory layer in `../pmg` grew out of it, and new work happens there.

```bash
cd legacy
pip install -r requirements.txt
cp config.example.json config.json   # add your API keys; config.json is gitignored
python -m uvicorn server:app --host 127.0.0.1 --port 8081
```

On Windows, run `start.bat` instead. Chat messages are stored locally in `legacy/data/` (SQLite).
