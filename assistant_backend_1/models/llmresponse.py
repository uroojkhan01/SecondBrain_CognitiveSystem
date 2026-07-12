from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class LLMResponse:
    intent: str
    reply_to_user: str
    memory_summary: Optional[str] = None
    entities: List[dict] = field(default_factory=list)
    follow_up_question: Optional[str] = None
    reminder: Optional[dict] = None
    task: Optional[dict] = None
    habit: Optional[dict] = None
    items: List[dict] = field(default_factory=list)  # for brain_dump
