import json
from groq import Groq
from assistant_backend_1.config import GROQ_API_KEY
from assistant_backend_1.prompts import CLASSIFIER_SYSTEM_PROMPT, NEO4J_CONTEXT_PROMPT
from assistant_backend_1.models.llmresponse import LLMResponse
from assistant_backend_1.features_services.memory_journal import (
    get_user_context,
    save_memory,
    save_reminder,
    save_task,
    save_habit,
    mark_task_done,
    update_entity
)
from assistant_backend_1.features_services.notion import (
    save_task_to_notion,
    save_reminder_to_notion
)

client = Groq(api_key=GROQ_API_KEY)

conversation_histories: dict[str, list] = {}

INTENTS_TO_SKIP_SAVING = {
    "conversation",
    "seek_advice",
    "daily_brief",
    "panic_mode"
}


def build_system_prompt(chat_id: str) -> str:
    """Build enriched system prompt with Neo4j long term memory and current time."""
    import pytz
    from datetime import datetime

    # Her timezone code — untouched
    berlin_tz = pytz.timezone("Europe/Berlin")
    now_berlin = datetime.now(berlin_tz)
    current_time = now_berlin.strftime("%Y-%m-%dT%H:%M:%S")
    utc_offset = now_berlin.strftime("%z")
    formatted_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"

    time_block = f"""
Current date and time is: {current_time} (Europe/Berlin, UTC{formatted_offset})
Always include timezone offset in all datetime extractions.
Format: YYYY-MM-DDTHH:MM:SS{formatted_offset}
Example: if user says 3pm tomorrow and today is {now_berlin.strftime('%Y-%m-%d')}, extract: {(now_berlin).strftime('%Y-%m-%d')}T15:00:00{formatted_offset}
"""

    # My Neo4j context
    context = get_user_context(chat_id)
    context_block = NEO4J_CONTEXT_PROMPT.format(context=context)

    return f"{CLASSIFIER_SYSTEM_PROMPT}{time_block}\n\n{context_block}"


def handle_brain_dump(chat_id: str, items: list):
    """Handle multiple intents extracted from a brain dump."""
    for item in items:
        intent = item.get("intent")
        if intent == "create_task" and item.get("task"):
            save_task(
                chat_id,
                item["task"].get("title"),
                item["task"].get("due")
            )
        elif intent == "set_reminder" and item.get("reminder"):
            save_reminder(
                chat_id,
                item["reminder"].get("text"),
                item["reminder"].get("datetime")
            )
        elif intent == "save_memory" and item.get("memory_summary"):
            save_memory(
                chat_id,
                item["memory_summary"],
                item.get("entities", [])
            )


def route_intent(chat_id: str, llm_response: LLMResponse):
    """Route LLM response to correct save function based on intent."""

    intent = llm_response.intent

    if intent in INTENTS_TO_SKIP_SAVING:
        return

    elif intent == "save_memory":
        if llm_response.memory_summary:
            save_memory(
                chat_id,
                llm_response.memory_summary,
                llm_response.entities
            )

    elif intent == "vent":
        # Empathy reply but still save if there's personal content
        if llm_response.memory_summary:
            save_memory(
                chat_id,
                llm_response.memory_summary,
                llm_response.entities
            )

    elif intent == "set_reminder":
        if llm_response.reminder:
            # Save to Neo4j
            save_reminder(
                chat_id,
                llm_response.reminder.get("text"),
                llm_response.reminder.get("datetime")
            )
            # Her Notion integration — untouched
            save_reminder_to_notion(
                chat_id,
                llm_response.reminder.get("text"),
                llm_response.reminder.get("datetime")
            )

    elif intent == "create_task":
        if llm_response.task:
            # Save to Neo4j
            save_task(
                chat_id,
                llm_response.task.get("title"),
                llm_response.task.get("due")
            )
            # Her Notion integration — untouched
            save_task_to_notion(
                chat_id,
                llm_response.task.get("title"),
                llm_response.task.get("due")
            )

    elif intent == "habit_track":
        if llm_response.habit:
            save_habit(
                chat_id,
                llm_response.habit.get("name"),
                llm_response.habit.get("value")
            )

    elif intent == "mark_done":
        if llm_response.task:
            mark_task_done(chat_id, llm_response.task.get("title"))

    elif intent == "update_memory":
        if llm_response.entities:
            update_entity(chat_id, llm_response.entities)
        # Also save correction as a new memory
        if llm_response.memory_summary:
            save_memory(chat_id, llm_response.memory_summary, [])

    elif intent == "brain_dump":
        if llm_response.items:
            handle_brain_dump(chat_id, llm_response.items)


def process_user_input(chat_id: str, user_input: str) -> str:
    """
    Takes user message, runs through Groq LLM,
    classifies intent, saves to Neo4j + Notion, returns reply for Telegram.
    """

    if chat_id not in conversation_histories:
        conversation_histories[chat_id] = []

    history = conversation_histories[chat_id]
    history.append({"role": "user", "content": user_input})

    try:
        system_prompt = build_system_prompt(chat_id)

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": system_prompt},
                *history
            ]
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        llm_response = LLMResponse(
            intent=data.get("intent", "conversation"),
            reply_to_user=data.get("reply_to_user", "I'm here, tell me more."),
            memory_summary=data.get("memory_summary"),
            entities=data.get("entities", []),
            follow_up_question=data.get("follow_up_question"),
            reminder=data.get("reminder"),
            task=data.get("task"),
            habit=data.get("habit"),
            items=data.get("items", [])
        )

        history.append({"role": "assistant", "content": raw})

        if len(history) > 20:
            conversation_histories[chat_id] = history[-20:]

        print(
            f"[LLM] Intent: {llm_response.intent} | Reply: {llm_response.reply_to_user}")
        print(f"[LLM] Entities: {llm_response.entities}")
        print(f"[LLM] Memory: {llm_response.memory_summary}")

        route_intent(chat_id, llm_response)

        return llm_response.reply_to_user

    except json.JSONDecodeError as e:
        print(f"[LLM] JSON parse error: {e}")
        return "Sorry, I had trouble understanding that. Could you say it again?"

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Something went wrong on my end. Please try again!"
