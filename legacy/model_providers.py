"""
Flexible Model Provider System for JARVIS
Supports multiple AI model APIs and providers
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional
import httpx


class BaseModelProvider(ABC):
    """Base class for all model providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
    
    @abstractmethod
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses"""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is accessible"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> list:
        """Get list of available models"""
        pass


class OllamaProvider(BaseModelProvider):
    """Ollama local model provider"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.api_endpoint = f"{self.base_url}/api/chat"
    
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from Ollama"""
        options = {
            "num_ctx": kwargs.get("num_ctx", 2048),
            "num_predict": kwargs.get("num_predict", 300),
            "temperature": kwargs.get("temperature", 0.6),
            "top_p": kwargs.get("top_p", 0.9),
            "repeat_penalty": kwargs.get("repeat_penalty", 1.1),
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.api_endpoint,
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "keep_alive": "30m",
                    "options": options,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
    
    async def health_check(self) -> bool:
        """Check if Ollama is running"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
    
    def get_available_models(self) -> list:
        """Get available Ollama models"""
        # Return configured models from config file
        return self.config.get("models", ["gemma4:latest"])


class OpenAIProvider(BaseModelProvider):
    """OpenAI API provider"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.api_endpoint = f"{self.base_url}/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from OpenAI"""
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 300),
            "top_p": kwargs.get("top_p", 1.0),
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.api_endpoint,
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
    
    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible"""
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self.headers
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False
    
    def get_available_models(self) -> list:
        """Get available OpenAI models"""
        return self.config.get("models", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])


class AnthropicProvider(BaseModelProvider):
    """Anthropic Claude API provider"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.anthropic.com")
        self.api_endpoint = f"{self.base_url}/v1/messages"
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
    
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from Anthropic"""
        if not self.api_key:
            raise ValueError("Anthropic API key is required")
        
        # Convert messages to Anthropic format
        system_message = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        payload = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", 300),
            "stream": True,
            "system": system_message,
            "messages": anthropic_messages,
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.api_endpoint,
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        chunk = json.loads(data_str)
                        if chunk.get("type") == "content_block_delta":
                            token = chunk.get("delta", {}).get("text", "")
                            if token:
                                yield token
                    except json.JSONDecodeError:
                        continue
    
    async def health_check(self) -> bool:
        """Check if Anthropic API is accessible"""
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Simple health check - try to access a minimal endpoint
                response = await client.post(
                    self.api_endpoint,
                    headers=self.headers,
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "Hi"}]
                    }
                )
                return response.status_code in [200, 400, 401]  # Any response means API is up
        except httpx.HTTPError:
            return False
    
    def get_available_models(self) -> list:
        """Get available Anthropic models"""
        return self.config.get("models", ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"])


class HuggingFaceProvider(BaseModelProvider):
    """HuggingFace Inference API provider"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api-inference.huggingface.co")
        self.headers = {}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
    
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from HuggingFace"""
        # Convert messages to prompt format
        prompt = self._messages_to_prompt(messages)
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": kwargs.get("max_tokens", 300),
                "temperature": kwargs.get("temperature", 0.7),
                "top_p": kwargs.get("top_p", 0.9),
                "stream": True,
            }
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/models/{model}",
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        if isinstance(chunk, list) and len(chunk) > 0:
                            token = chunk[0].get("generated_text", "")
                            if token:
                                yield token
                    except json.JSONDecodeError:
                        # Try raw text
                        if line:
                            yield line
    
    def _messages_to_prompt(self, messages: list) -> str:
        """Convert messages to prompt format"""
        prompt = ""
        for msg in messages:
            if msg["role"] == "system":
                prompt += f"System: {msg['content']}\n"
            elif msg["role"] == "user":
                prompt += f"User: {msg['content']}\n"
            elif msg["role"] == "assistant":
                prompt += f"Assistant: {msg['content']}\n"
        prompt += "Assistant:"
        return prompt
    
    async def health_check(self) -> bool:
        """Check if HuggingFace API is accessible"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self.headers
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False
    
    def get_available_models(self) -> list:
        """Get available HuggingFace models"""
        return self.config.get("models", ["meta-llama/Llama-2-7b-chat-hf", "mistralai/Mistral-7B-Instruct-v0.2"])


class CustomAPIProvider(BaseModelProvider):
    """Custom API provider for any OpenAI-compatible endpoint"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.default_model = config.get("model", "custom-model")
        self.api_endpoint = f"{self.base_url}/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
    
    async def chat_stream(
        self, 
        messages: list, 
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream chat responses from custom API"""
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 300),
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.api_endpoint,
                headers=self.headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        # Try common response formats
                        token = ""
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            token = chunk["choices"][0].get("delta", {}).get("content", "")
                        elif "message" in chunk:
                            token = chunk["message"].get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
    
    async def health_check(self) -> bool:
        """Check if custom API is accessible"""
        if not self.base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self.headers
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False
    
    def get_available_models(self) -> list:
        """Return configured models"""
        models = self.config.get("models", [])
        if not models and self.default_model:
            return [self.default_model]
        return models


def get_provider(provider_name: str, config: Dict[str, Any]) -> BaseModelProvider:
    """Factory function to get provider instance"""
    providers = {
        "ollama": OllamaProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "huggingface": HuggingFaceProvider,
        "custom": CustomAPIProvider,
    }
    
    provider_class = providers.get(provider_name.lower())
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_name}")
    
    return provider_class(config)
