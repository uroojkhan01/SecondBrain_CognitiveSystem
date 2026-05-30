import json
from groq import Groq
from assistant_backend_1.config import GROQ_API_KEY
from assistant_backend_1.prompts import CLASSIFIER_SYSTEM_PROMPT
from assistant_backend_1.models.llmresponse import LLMResponse

client = Groq(api_key=GROQ_API_KEY)

conversation_histories: dict[str, list] = {}


def process_user_input(chat_id: str, user_input: str) -> str:
    """
    Takes user message, runs it through Groq LLM,
    classifies intent, extracts data, returns reply string for Telegram.
    """

    # Build or retrieve conversation history for this user
    if chat_id not in conversation_histories:
        conversation_histories[chat_id] = []

    history = conversation_histories[chat_id]

    # Add user message to history
    history.append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},  # forces valid JSON
            temperature=0.2,                           # consistent, reliable output
            max_tokens=1024,
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
                *history                               # full conversation context
            ]
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)

        # Parse into model
        llm_response = LLMResponse(
            intent=data.get("intent", "conversation"),
            reply_to_user=data.get("reply_to_user", "I'm here, tell me more."),
            memory_summary=data.get("memory_summary"),
            entities=data.get("entities", []),
            follow_up_question=data.get("follow_up_question"),
            reminder=data.get("reminder"),
            task=data.get("task")
        )

        # Add assistant reply to history
        history.append({"role": "assistant", "content": raw})

        # Keep history manageable (last 20 messages)
        if len(history) > 20:
            conversation_histories[chat_id] = history[-20:]

        print(
            f"[LLM] Intent: {llm_response.intent} | Reply: {llm_response.reply_to_user}")
        print(f"[LLM] Entities: {llm_response.entities}")
        print(f"[LLM] Memory: {llm_response.memory_summary}")

        # For now — just return the reply to user
        # Later: route to reminder/memory/notion services based on intent
        return llm_response.reply_to_user

    except json.JSONDecodeError as e:
        print(f"[LLM] JSON parse error: {e}")
        return "Sorry, I had trouble understanding that. Could you say it again?"

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return "Something went wrong on my end. Please try again!"
