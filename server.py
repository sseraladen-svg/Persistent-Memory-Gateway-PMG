import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import memory
import model_providers

ROOT = Path(__file__).parent

# Load configuration
def load_config():
    config_path = ROOT / "config.json"
    example_config_path = ROOT / "config.example.json"
    
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    elif example_config_path.exists():
        # Copy example config as default
        import shutil
        shutil.copy(example_config_path, config_path)
        with open(config_path) as f:
            return json.load(f)
    else:
        return {
            "default_provider": "ollama",
            "default_model": "gemma4:latest",
            "providers": {
                "ollama": {
                    "enabled": True,
                    "base_url": "http://localhost:11434",
                    "models": ["gemma4:latest"]
                }
            },
            "generation_params": {
                "temperature": 0.7,
                "max_tokens": 300,
                "top_p": 0.9,
                "num_ctx": 2048
            }
        }

config = load_config()
current_provider = None
current_model = config.get("default_model", "gemma4:latest")
provider_name = config.get("default_provider", "ollama")

print(f"Loaded config - Provider: {provider_name}, Model: {current_model}")


async def initialize_provider():
    global current_provider, provider_name
    provider_config = config["providers"].get(provider_name, {})
    if provider_config.get("enabled", True):
        try:
            current_provider = model_providers.get_provider(provider_name, provider_config)
        except Exception as e:
            print(f"Error initializing provider {provider_name}: {e}")
            # Fallback to first available provider
            for p_name, p_config in config["providers"].items():
                if p_config.get("enabled", True):
                    try:
                        current_provider = model_providers.get_provider(p_name, p_config)
                        provider_name = p_name
                        break
                    except:
                        continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_provider()
    yield


app = FastAPI(lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=ROOT), name="static")


class ChatRequest(BaseModel):
    message: str
    session_id: str
    provider: str = None
    model: str = None


class SettingsRequest(BaseModel):
    openai_key: str = None
    anthropic_key: str = None
    huggingface_key: str = None
    custom_key: str = None
    custom_endpoint: str = None
    custom_model: str = None
    temperature: float = None
    max_tokens: int = None


def build_messages(history: list):
    learned = memory.get_learned_context()
    messages = [{"role": "system", "content": memory.SYSTEM}]
    if learned:
        messages.append({"role": "system", "content": learned})
    messages.extend(history)
    return messages


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/api/health")
async def health():
    provider_ok = False
    if current_provider:
        provider_ok = await current_provider.health_check()
    
    return {
        "provider": provider_name,
        "model": current_model,
        "provider_status": "ok" if provider_ok else "error",
        **memory.status()
    }


@app.get("/api/providers")
async def get_providers():
    """Get available providers and their models"""
    providers_info = {}
    for p_name, provider_config in config["providers"].items():
        if provider_config.get("enabled", True):
            try:
                provider = model_providers.get_provider(p_name, provider_config)
                providers_info[p_name] = {
                    "enabled": True,
                    "models": provider.get_available_models(),
                    "config": {k: v for k, v in provider_config.items() if k != "api_key"}
                }
            except Exception as e:
                providers_info[p_name] = {
                    "enabled": True,
                    "error": str(e),
                    "models": []
                }
        else:
            providers_info[p_name] = {
                "enabled": False,
                "models": []
            }
    
    return {
        "current_provider": provider_name,
        "current_model": current_model,
        "providers": providers_info
    }


@app.post("/api/switch_provider")
async def switch_provider(provider_data: dict):
    """Switch to a different provider/model"""
    global current_provider, current_model, provider_name
    
    new_provider = provider_data.get("provider")
    new_model = provider_data.get("model")
    
    if new_provider not in config["providers"]:
        return {"error": f"Provider {new_provider} not configured"}
    
    provider_config = config["providers"][new_provider]
    if not provider_config.get("enabled", True):
        return {"error": f"Provider {new_provider} is disabled"}
    
    try:
        current_provider = model_providers.get_provider(new_provider, provider_config)
        provider_name = new_provider
        current_model = new_model or provider_config.get("models", [""])[0]
        
        # Verify provider is accessible
        if not await current_provider.health_check():
            return {"error": f"Provider {new_provider} is not accessible"}
        
        return {
            "success": True,
            "provider": provider_name,
            "model": current_model
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/settings")
async def save_settings(settings: SettingsRequest):
    """Save user settings to config"""
    global config
    
    if settings.openai_key:
        config["providers"]["openai"]["api_key"] = settings.openai_key
        config["providers"]["openai"]["enabled"] = True
    
    if settings.anthropic_key:
        config["providers"]["anthropic"]["api_key"] = settings.anthropic_key
        config["providers"]["anthropic"]["enabled"] = True
    
    if settings.huggingface_key:
        config["providers"]["huggingface"]["api_key"] = settings.huggingface_key
        config["providers"]["huggingface"]["enabled"] = True
    
    if settings.custom_key:
        config["providers"]["custom"]["api_key"] = settings.custom_key
        config["providers"]["custom"]["enabled"] = True
    
    if settings.custom_endpoint:
        config["providers"]["custom"]["base_url"] = settings.custom_endpoint
        config["providers"]["custom"]["enabled"] = True
    
    if settings.custom_model:
        config["providers"]["custom"]["models"] = [settings.custom_model]
        config["providers"]["custom"]["enabled"] = True
    
    if settings.temperature is not None:
        config["generation_params"]["temperature"] = settings.temperature
    
    if settings.max_tokens is not None:
        config["generation_params"]["max_tokens"] = settings.max_tokens
    
    # Save to config file
    try:
        with open(ROOT / "config.json", "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        return {"error": f"Failed to save config: {str(e)}"}
    
    # Reinitialize provider if needed
    await initialize_provider()
    
    return {"success": True, "message": "Settings saved successfully"}


@app.get("/api/memory")
def list_memory():
    return {"learned": memory.get_learned_facts()}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    global current_provider, current_model
    
    # Use provider/model from request or defaults
    provider = req.provider or provider_name
    model = req.model or current_model
    
    # Switch provider if requested
    if provider != provider_name:
        try:
            provider_config = config["providers"].get(provider, {})
            current_provider = model_providers.get_provider(provider, provider_config)
            current_model = model
        except Exception as e:
            async def error_stream():
                yield f"Error switching provider: {str(e)}"
            return StreamingResponse(error_stream(), media_type="text/plain")
    
    if not current_provider:
        async def error_stream():
            yield "Error: No provider configured"
        return StreamingResponse(error_stream(), media_type="text/plain")
    
    learned_cat, history = await asyncio.gather(
        asyncio.to_thread(memory.learn_from_message, req.message),
        asyncio.to_thread(memory.get_history, req.session_id, 6),
    )
    await asyncio.to_thread(memory.save_message, req.session_id, "user", req.message)
    history = history + [{"role": "user", "content": req.message}]
    messages = build_messages(history)

    headers = {"X-Learned": learned_cat} if learned_cat else {}
    gen_params = config.get("generation_params", {})

    async def stream():
        reply = ""
        try:
            async for token in current_provider.chat_stream(
                messages=messages,
                model=model,
                **gen_params
            ):
                reply += token
                yield token
        except Exception as e:
            yield f"\n[Error: {type(e).__name__} — {str(e)}]"
            return
        finally:
            if reply:
                await asyncio.to_thread(memory.save_message, req.session_id, "assistant", reply)
                await asyncio.to_thread(memory.cache_session, req.session_id, history)

    return StreamingResponse(stream(), media_type="text/plain", headers=headers)
