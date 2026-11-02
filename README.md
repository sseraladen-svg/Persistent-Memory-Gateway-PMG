# AI Assistant-PMG

<div align="center">

**A Modern, Multi-Model AI Assistant with Voice Input & Custom Provider Support**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

[⚡ Features](#-features) • [🚀 Installation](#-installation) • [🎯 Providers](#-supported-providers) • [🎨 Frontend](#-modern-frontend) • [📖 API](#-api-endpoints)

</div>

---

## ✨ Features

- 🎯 **Multi-Model Support** - Switch between Ollama, OpenAI, Anthropic, HuggingFace, and Custom APIs
- 🎤 **Voice Input** - Speech-to-text for hands-free chatting
- 🎨 **Modern UI** - Beautiful dark theme with gradient accents
- ⚙️ **Settings Panel** - Configure API keys and parameters in-app
- 🧠 **Memory System** - JARVIS learns and remembers information
- 🔄 **Streaming Responses** - Real-time AI responses
- 🔒 **Privacy-Focused** - No chat history storage, secure API key handling
- 📊 **Health Monitoring** - Real-time connection status

---

## 🚀 Installation

### Prerequisites

- Python 3.11 or higher
- Ollama (for local models) or API keys for cloud providers

### Step 1: Clone the Repository

```bash
git clone https://github.com/sseraladen-svg/Jarvis.git
cd Jarvis
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Configure JARVIS

```bash
cp config.example.json config.json
```

Edit `config.json` to add your API keys and configure providers.

### Step 4: Start the Server

**Windows:**
```bash
start.bat
```

**Linux/macOS:**
```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8081
```

Visit `http://127.0.0.1:8081` to access JARVIS!

---

## 🎯 Supported Providers

### 1. 🦙 Ollama (Local Models)

**Best for:** Privacy, free local inference, custom models

```json
{
  "ollama": {
    "enabled": true,
    "base_url": "http://localhost:11434",
    "models": ["gemma4:latest", "llama3.1:8b", "mistral:latest"]
  }
}
```

**Setup:**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull gemma4
ollama pull llama3.1
```

### 2. 🔵 OpenAI

**Best for:** GPT-4, GPT-3.5, reliable performance

```json
{
  "openai": {
    "enabled": true,
    "api_key": "sk-your-openai-api-key",
    "base_url": "https://api.openai.com/v1",
    "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
  }
}
```

### 3. 🟣 Anthropic Claude

**Best for:** Claude 3.5 Sonnet, long context, analysis tasks

```json
{
  "anthropic": {
    "enabled": true,
    "api_key": "sk-ant-your-anthropic-api-key",
    "base_url": "https://api.anthropic.com",
    "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
  }
}
```

### 4. 🤗 HuggingFace

**Best for:** Open-source models, custom model deployment

```json
{
  "huggingface": {
    "enabled": true,
    "api_key": "hf-your-huggingface-token",
    "base_url": "https://api-inference.huggingface.co",
    "models": ["meta-llama/Llama-2-7b-chat-hf", "mistralai/Mistral-7B-Instruct-v0.2"]
  }
}
```

### 5. 🔧 Custom API

**Best for:** Self-hosted models, OpenAI-compatible endpoints

```json
{
  "custom": {
    "enabled": true,
    "api_key": "your-custom-api-key",
    "base_url": "https://your-custom-endpoint.com/v1",
    "models": ["custom-model-name"]
  }
}
```

---

## 🎨 Modern Frontend

### Beautiful Dark Theme

- Gradient accents with purple/blue color scheme
- Smooth animations and transitions
- Responsive design for all screen sizes
- Intuitive navigation sidebar

### Voice Input

- 🎤 Click the microphone button to start voice input
- 🗣️ Speak naturally, JARVIS transcribes your speech
- ⏹️ Click again to stop recording

### Settings Panel

- Configure API keys securely in the UI
- Adjust generation parameters (temperature, max tokens)
- Set custom model endpoints
- Settings are saved to `config.json` automatically

### Model Selection

- Dynamic provider switching
- Real-time model availability
- Status indicators for connection health

---

## 📖 API Endpoints

### Health Check

```bash
GET /api/health
```

**Response:**
```json
{
  "provider": "ollama",
  "model": "gemma4:latest",
  "provider_status": "ok",
  "sqlite": {"ok": true, "messages": 5, "learned": 0},
  "chromadb": {"ok": true, "memories": 0},
  "redis": {"ok": true, "mode": "embedded"}
}
```

### Get Providers

```bash
GET /api/providers
```

**Response:**
```json
{
  "current_provider": "ollama",
  "current_model": "gemma4:latest",
  "providers": {
    "ollama": {
      "enabled": true,
      "models": ["gemma4:latest", "llama3.1:8b"],
      "config": {"base_url": "http://localhost:11434"}
    }
  }
}
```

### Switch Provider

```bash
POST /api/switch_provider
Content-Type: application/json

{
  "provider": "openai",
  "model": "gpt-4o"
}
```

### Chat

```bash
POST /api/chat
Content-Type: application/json

{
  "message": "Hello JARVIS!",
  "session_id": "session_123",
  "provider": "ollama",
  "model": "gemma4:latest"
}
```

**Response:** Streaming text content

### Save Settings

```bash
POST /api/settings
Content-Type: application/json

{
  "openai_key": "sk-...",
  "temperature": 0.8,
  "max_tokens": 400
}
```

### Memory

```bash
GET /api/memory
```

---

## 🔧 Configuration

### Generation Parameters

```json
{
  "generation_params": {
    "temperature": 0.7,
    "max_tokens": 300,
    "top_p": 0.9,
    "num_ctx": 2048
  }
}
```

- **temperature**: Controls randomness (0.0 = deterministic, 1.0 = creative)
- **max_tokens**: Maximum response length
- **top_p**: Nucleus sampling threshold
- **num_ctx**: Context window size (Ollama specific)

---

## 🔒 Security

- ✅ API keys stored in `config.json` (gitignored)
- ✅ Settings panel for secure key management
- ✅ No chat history storage (privacy-focused)
- ✅ Local-first with Ollama option
- ✅ Environment variable support

**⚠️ Important:** Never commit `config.json` with real API keys to git!

---

## 🐛 Troubleshooting

### Provider Connection Failed

- **Ollama**: Ensure `ollama serve` is running
- **Cloud APIs**: Verify your API keys are valid
- **Custom**: Check your endpoint is accessible

### Model Not Available

- Verify model name in config.json
- For Ollama: Check `ollama list`
- For cloud APIs: Ensure you have access to the model

### Voice Input Not Working

- Use Chrome or Edge for best Web Speech API support
- Check microphone permissions
- Ensure you're using HTTPS (or localhost)

### Database Errors

- Ensure `data/` directory exists
- Check file permissions
- Delete `data/jarvis.db*` to reset database

---

## 📁 Project Structure

```
Jarvis/
├── data/              # Database and ChromaDB storage
│   ├── jarvis.db      # SQLite database
│   └── chroma/        # Vector embeddings
├── server.py          # FastAPI backend
├── memory.py          # Memory management system
├── model_providers.py # Multi-provider system
├── config.json        # Your configuration (gitignored)
├── config.example.json # Example configuration
├── index.html         # Modern web interface
├── requirements.txt   # Python dependencies
├── start.bat          # Windows startup script
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [Ollama](https://ollama.com) for local model support
- [FastAPI](https://fastapi.tiangolo.com) for the web framework
- [Anthropic](https://www.anthropic.com) for Claude API
- [OpenAI](https://openai.com) for GPT models
- [HuggingFace](https://huggingface.co) for open-source models

---

<div align="center">

**Built with ❤️ by the JARVIS Team**

[⬆ Back to Top](#-jarvis-ai-assistant)

</div>
