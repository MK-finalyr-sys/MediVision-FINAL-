"""Tiny proxy module that re-exports SYSTEM_PROMPT from app.chatbot.

This exists so integrations.meditron_chat can use the same safety prompt as
the Gemini path without creating a circular import (app.chatbot imports from
app.retriever and app.data; integrations.meditron_chat would create a chain
if it imported app.chatbot directly at module-load time).
"""
from app.chatbot import SYSTEM_PROMPT   # noqa: F401
