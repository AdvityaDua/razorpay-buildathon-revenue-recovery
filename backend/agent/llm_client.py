"""
LLM client — ChatOpenAI wrapper pointed at NVIDIA Nemotron endpoint.

Reads LLM_BASE_URL, LLM_MODEL_NAME, LLM_API_KEY from .env.
Native tool-calling enabled.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load .env from project root
load_dotenv()


def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """
    Get a ChatOpenAI instance pointed at the NVIDIA Nemotron endpoint.

    Low temperature by default for reproducible eval runs
    (eval-harness-conventions skill: determinism for reproducibility).
    """
    base_url = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    model_name = os.getenv("LLM_MODEL_NAME", "nvidia/nemotron-3-ultra-550b-a55b")
    api_key = os.getenv("LLM_API_KEY", "not-needed")

    return ChatOpenAI(
        base_url=base_url,
        model=model_name,
        api_key=api_key,
        temperature=temperature,
        max_tokens=2048,
    )
