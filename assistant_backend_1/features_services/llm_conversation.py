import json
from groq import Groq
import anthropic
from assistant_backend_1.config import GROQ_API_KEYS, ANTHROPIC_API_KEY
from assistant_backend_1.prompts import CLASSIFIER_SYSTEM_PROMPT, NEO4J_CONTEXT_PROMPT
from assistant_backend_1.models.llmresponse import LLMResponse
from assistant_backend_1.features_services.reminders import get_all_reminders, delete_reminder,update_reminder
from assistant_backend_1.features_services.memory_journal import (
    get_user_context,
    save_memory,
    save_reminder,
    save_task,
    save_habit,
    mark_task_done,
    mark_reminder_done,
    update_entity,
    get_all_tasks,
    delete_local_task,
    update_local_task
)
from assistant_backend_1.features_services.notion import (
    save_task_to_notion,
    delete_task_from_notion,
    update_task_in_notion,
    save_reminder_to_notion,
    mark_task_done_in_notion,
)

from assistant_backend_1.models.db_hooks import (
    hook_save_task,
    hook_save_reminder,
    hook_mark_task_done,
    hook_cancel_task,
)


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
            title = item["task"].get("title")
            due = item["task"].get("due")
            criticality = item["task"].get("criticality")
            save_task(chat_id, title, due)
            save_task_to_notion(chat_id, title, due, criticality)
            hook_save_task(chat_id, item["task"].get("title"), due_date=item["task"].get("due"))
        elif intent == "set_reminder" and item.get("reminder"):
            save_reminder(
                chat_id,
                item["reminder"].get("text"),
                item["reminder"].get("datetime")
            )
            hook_save_reminder(chat_id, item["reminder"].get("text"), remind_at=item["reminder"].get("datetime"))
        elif intent == "save_memory" and item.get("memory_summary"):
            save_memory(
                chat_id,
                item["memory_summary"],
                item.get("entities", [])
            )


def route_intent(chat_id: str, llm_response: LLMResponse, user_input: str):
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
        if llm_response.memory_summary:
            save_memory(
                chat_id,
                llm_response.memory_summary,
                llm_response.entities
            )

    elif intent == "set_reminder":
        if llm_response.reminder:
            text = llm_response.reminder.get("text")
            remind_at = llm_response.reminder.get("datetime")
            if text and remind_at:
                save_reminder(chat_id, text, remind_at)
                hook_save_reminder(chat_id, text, remind_at=remind_at)
                save_task_to_notion(chat_id, text, remind_at, criticality=None)
            else:
                print(f"⏳ Reminder incomplete (missing {'datetime' if not remind_at else 'text'}) — waiting for more info.")

    elif intent == "delete_reminder":
        if llm_response.reminder:
            reminder_text = llm_response.reminder.get("text", "")
            all_reminders = get_all_reminders(chat_id)
            matched = next(
                (r for r in all_reminders
                 if reminder_text.lower() in r["name"].lower()
                 or r["name"].lower() in reminder_text.lower()),
                None
            )
            if matched:
                success = delete_reminder(chat_id, matched["id"])
                print(f"{'✅' if success else '❌'} Delete reminder: {reminder_text}")
            else:
                print(f"⚠️ No matching reminder found for: {reminder_text}")
            delete_task_from_notion(chat_id, reminder_text)
            from assistant_backend_1.models.db import get_user_by_chat_id, get_reminders_for_user, delete_reminder as db_delete_reminder
            user = get_user_by_chat_id(chat_id)
            if user:
                reminders = get_reminders_for_user(user["id"], include_sent=True)
                for r in reminders:
                    if reminder_text.lower() in r["text"].lower():
                        db_delete_reminder(r["id"])
                        print(f"[DB] ✅ Reminder deleted from Postgres: {reminder_text}")
                        break


    elif intent == "update_reminder":
        if llm_response.reminder:
            reminder_text = llm_response.reminder.get("text", "")
            new_datetime = llm_response.reminder.get("datetime")
            new_text = llm_response.reminder.get("new_text")
            all_reminders = get_all_reminders(chat_id)
            matched = next(
                (r for r in all_reminders
                 if reminder_text.lower() in r["name"].lower()
                 or r["name"].lower() in reminder_text.lower()),
                None
            )
            hook_save_reminder(chat_id, reminder_text, remind_at=new_datetime)
            if matched:
                success = update_reminder(
                    chat_id,
                    matched["id"],
                    text=new_text,
                    remind_at=new_datetime
                )
                print(f"{'✅' if success else '❌'} Update reminder: {reminder_text}")
            else:
                print(f"⚠️ No matching reminder found for: {reminder_text}")
            update_task_in_notion(chat_id, reminder_text, new_title=new_text, new_due=new_datetime)

    elif intent == "create_task":
        if llm_response.task:
            title = llm_response.task.get("title")
            due = llm_response.task.get("due")
            criticality = llm_response.task.get("criticality")
            save_task(chat_id, title, due)
            save_task_to_notion(chat_id, title, due, criticality)
            hook_save_task(chat_id, title, due_date=due)

    elif intent == "delete_task":
        if llm_response.task:
            task_title = llm_response.task.get("title", "")
            all_tasks = get_all_tasks(chat_id)
            matched = next(
                (t for t in all_tasks
                 if task_title.lower() in t["title"].lower()
                 or t["title"].lower() in task_title.lower()),
                None
            )
            if matched:
                success = delete_local_task(chat_id, matched["id"])
                print(f"{'✅' if success else '❌'} Delete task (Neo4j): {task_title}")
            else:
                print(f"⚠️ No matching task found in Neo4j: {task_title}")
            delete_task_from_notion(chat_id, task_title)
            hook_cancel_task(chat_id, task_title)

    elif intent == "update_task":
        if llm_response.task:
            task_title = llm_response.task.get("title", "")
            new_title = llm_response.task.get("new_title")
            new_due = llm_response.task.get("due")
            all_tasks = get_all_tasks(chat_id)
            matched = next(
                (t for t in all_tasks
                 if task_title.lower() in t["title"].lower()
                 or t["title"].lower() in task_title.lower()),
                None
            )
            hook_save_task(chat_id, llm_response.task.get("title"), due_date=llm_response.task.get("due"))
            if matched:
                success = update_local_task(chat_id, matched["id"], title=new_title, due=new_due)
                print(f"{'✅' if success else '❌'} Update task (Neo4j): {task_title}")
            else:
                print(f"⚠️ No matching task found in Neo4j: {task_title}")
            update_task_in_notion(chat_id, task_title, new_title=new_title, new_due=new_due)


    elif intent == "habit_track":
        if llm_response.habit:
            save_habit(
                chat_id,
                llm_response.habit.get("name"),
                llm_response.habit.get("value")
            )

    elif intent == "mark_done":
        if llm_response.task:
            title = llm_response.task.get("title")
            mark_task_done(chat_id, title)
            mark_reminder_done(chat_id, title)
            hook_mark_task_done(chat_id, title)
            mark_task_done_in_notion(chat_id, title)

            

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
    Takes user message, runs through Groq LLM first.
    If all Groq API keys fail, switches to Claude as fallback.
    Classifies intent, saves to Neo4j + Notion, returns reply for Telegram.
    """
    if chat_id not in conversation_histories:
        conversation_histories[chat_id] = []
    
    history = conversation_histories[chat_id]
    history.append({"role": "user", "content": user_input})
    
    try:
        system_prompt = build_system_prompt(chat_id)
        response = None
        last_exception = None
        used_claude = False

        # ─────────────────────────────────────────
        # STEP 1: Try all Groq API keys first
        # ─────────────────────────────────────────
        for api_key in GROQ_API_KEYS:
            try:
                temp_client = Groq(api_key=api_key)
                response = temp_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *history
                    ]
                )
                print(f"[LLM] Using Groq with key: {str(api_key)[:5]}...")
                break
            except Exception as e:
                print(f"[LLM] Groq key {str(api_key)[:5]}... failed: {e}")
                last_exception = e
                continue

        # ─────────────────────────────────────────
        # STEP 2: All Groq keys failed → fallback to Claude
        # ─────────────────────────────────────────
        if response is None:
            print(f"[LLM] All Groq keys exhausted. Switching to Claude fallback...")
            try:
                if not ANTHROPIC_API_KEY:
                    raise Exception("ANTHROPIC_API_KEY not set in environment.")
                
                claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                
                # Claude requires system prompt separately, not in messages array
                claude_response = claude_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1024,
                    temperature=0.2,
                    system=system_prompt,
                    messages=history  # same history format works for Claude
                )
                
                # Normalize Claude response to match Groq response structure
                raw = claude_response.content[0].text
                used_claude = True
                print(f"[LLM] Claude fallback succeeded.")

            except Exception as claude_error:
                print(f"[LLM] Claude fallback also failed: {claude_error}")
                # Both Groq and Claude failed — raise original Groq error
                if last_exception:
                    raise last_exception
                raise Exception("All LLM providers failed.")
        else:
            # Groq succeeded — extract raw text normally
            raw = response.choices[0].message.content

        # ─────────────────────────────────────────
        # STEP 3: Parse response (same for both providers)
        # ─────────────────────────────────────────
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        data = json.loads(cleaned)
        
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

        provider = "Claude" if used_claude else "Groq"
        print(f"[LLM] Provider: {provider} | Intent: {llm_response.intent} | Reply: {llm_response.reply_to_user}")
        print(f"[LLM] Entities: {llm_response.entities}")
        print(f"[LLM] Memory: {llm_response.memory_summary}")

        route_intent(chat_id, llm_response, user_input)
        return llm_response.reply_to_user

    except json.JSONDecodeError as e:
        print(f"[LLM] JSON parse error: {e}")
        return "Sorry, I had trouble understanding that. Could you say it again?"
    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Something went wrong on my end. Please try again!"
