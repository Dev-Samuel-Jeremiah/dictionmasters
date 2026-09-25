"""Generate type-aware Tricks assessment question drafts with OpenAI."""

import json
import urllib.error
import urllib.request

from django.conf import settings

from apps.echospell.activity_kinds import MODE_CHOICE, MODE_RECORD, MODE_SORT
from apps.manage.rich_text import plain_text


API_URL = "https://api.openai.com/v1/chat/completions"
TIMEOUT_SECONDS = 45
MAX_QUESTIONS = 30
MAX_GUIDANCE_LENGTH = 3000


class QuestionGenerationError(Exception):
    """The question draft could not be generated or did not pass validation."""


def _response_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "prompt": {"type": "string"},
                        "answer": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "hint": {"type": "string"},
                    },
                    "required": ["prompt", "answer", "options", "hint"],
                },
            },
        },
        "required": ["questions"],
    }


def _activity_context(activity, guidance):
    trick = activity.lesson
    kind = activity.kind_spec
    existing = [
        {"prompt": plain_text(prompt)[:240], "answer": answer[:240]}
        for prompt, answer in activity.items.order_by("order", "id").values_list("prompt", "answer")[:30]
    ]
    return {
        "programme": "Tricks to Sound Fluent",
        "trick": {
            "name": trick.name,
            "symbol": trick.symbol,
            "example_words": trick.example_words,
        },
        "assessment_activity": {
            "title": activity.title,
            "type": kind.label,
            "type_description": kind.summary,
            "learner_instructions": activity.display_instructions,
            "question_prompt_guidance": kind.prompt_help,
            "correct_answer_guidance": kind.answer_help,
            "multiple_choice_guidance": kind.options_help,
            "sorting_boxes": activity.bucket_list if kind.mode == MODE_SORT else [],
            "requires_recording": kind.mode == MODE_RECORD,
            "requires_audio_asset": kind.needs_audio,
            "requires_image_asset": kind.uses_image,
            "prompt_is_shown_to_learner": kind.uses_prompt,
        },
        "question_writing_guidance": guidance[:MAX_GUIDANCE_LENGTH],
        "avoid_repeating_existing_questions": existing,
    }


def _validate_questions(activity, questions, count):
    kind = activity.kind_spec
    if not isinstance(questions, list) or len(questions) != count:
        received = len(questions) if isinstance(questions, list) else 0
        raise QuestionGenerationError(
            f"The AI returned {received} questions; {count} were requested. Try generating again."
        )

    cleaned = []
    boxes = set(activity.bucket_list)
    for number, question in enumerate(questions, 1):
        if not isinstance(question, dict):
            raise QuestionGenerationError(f"Question {number} was not in a usable format. Try generating again.")
        prompt = str(question.get("prompt") or "").strip()
        answer = str(question.get("answer") or "").strip()
        options = question.get("options")
        hint = str(question.get("hint") or "").strip()[:200]
        if not isinstance(options, list) or any(not isinstance(option, str) for option in options):
            raise QuestionGenerationError(f"Question {number} has unusable answer options. Try generating again.")
        options = [option.strip() for option in options if option.strip()]

        # Audio-led activities keep this reference text out of the learner's
        # view while giving staff the words or script to record for each row.
        if kind.uses_prompt and not prompt:
            raise QuestionGenerationError(f"Question {number} is missing its prompt.")
        if kind.needs_audio and not prompt:
            raise QuestionGenerationError(f"Question {number} is missing its audio script or reference text.")
        if kind.mode != MODE_RECORD and not answer:
            raise QuestionGenerationError(f"Question {number} is missing its correct answer.")
        if kind.mode == MODE_CHOICE:
            if len(options) < 2:
                raise QuestionGenerationError(f"Question {number} needs at least two answer options.")
            if answer.casefold() not in {option.casefold() for option in options}:
                raise QuestionGenerationError(f"Question {number}'s correct answer is not one of its options.")
        else:
            options = []
        if kind.mode == MODE_SORT and answer not in boxes:
            raise QuestionGenerationError(f"Question {number}'s answer must match one of the activity's sorting boxes.")
        if kind.mode == MODE_RECORD:
            answer = ""
        cleaned.append({"prompt": prompt[:5000], "answer": answer[:5000],
                        "options": options, "hint": hint})
    return cleaned


def generate_questions(activity, count, guidance=""):
    """Return validated question drafts. Nothing is saved to the database."""
    if not getattr(settings, "OPENAI_API_KEY", ""):
        raise QuestionGenerationError("OpenAI is not configured. Add OPENAI_API_KEY in the server settings first.")
    if not activity.kind_spec:
        raise QuestionGenerationError("Select a valid assessment activity type first.")
    if activity.kind_spec.mode == MODE_SORT and len(activity.bucket_list) < 2:
        raise QuestionGenerationError("Add at least two sorting boxes to this activity before generating questions.")
    try:
        count = int(count)
    except (TypeError, ValueError) as error:
        raise QuestionGenerationError("Enter how many questions to generate.") from error
    if not 1 <= count <= MAX_QUESTIONS:
        raise QuestionGenerationError(f"Choose between 1 and {MAX_QUESTIONS} questions per generation.")

    context = _activity_context(activity, str(guidance or "").strip())
    kind = activity.kind_spec
    system_prompt = (
        "You create accurate, age-appropriate English pronunciation and fluency assessment questions "
        "for learners in Nigeria. Use British English spelling. Follow the requested activity type exactly, "
        "and base every item on the selected Trick and its examples. The activity's learner instructions "
        "describe what learners do; the separate question-writing guidance describes what the administrator "
        "wants in the question content. For multiple choice, provide plausible distractors and make the "
        "correct answer exactly one of the options. For sorting, the answer must exactly match one supplied "
        "sorting box. For recording tasks, provide a short, speakable prompt and an empty answer. For audio-led "
        "tasks, provide the private script/reference text staff should record; the application will not show that "
        "prompt to learners when the activity type hides it. Do not invent audio or image files. Avoid repeating "
        "the existing items. Generate exactly the requested number of distinct items. Return only the required data."
    )
    user_prompt = {
        "requested_question_count": count,
        "activity_context": context,
        "required_output_fields": {
            "prompt": "Question shown to learners, or private audio script/reference text for audio-led activities.",
            "answer": "Correct answer; empty string for teacher-marked recording tasks.",
            "options": "Array of options for multiple-choice activities; empty array otherwise.",
            "hint": "A short optional hint, or empty string.",
        },
    }
    body = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0.35,
        "max_completion_tokens": min(9000, 500 + count * 240),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "tricks_assessment_questions",
                "strict": True,
                "schema": _response_schema(),
            },
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "dictionmasters/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            detail = "OpenAI is busy or the API account has reached its current limit. Try again shortly."
        elif error.code in (401, 403):
            detail = "OpenAI rejected the configured API key. Check OPENAI_API_KEY in the server settings."
        else:
            detail = f"OpenAI could not complete the request (HTTP {error.code})."
        raise QuestionGenerationError(detail) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise QuestionGenerationError("Couldn't reach OpenAI. Check the server connection and try again.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise QuestionGenerationError("OpenAI returned an unreadable response. Try again.") from error

    try:
        choice = payload["choices"][0]
        message = choice["message"]
        if message.get("refusal"):
            raise QuestionGenerationError("OpenAI could not generate this question set. Adjust the guidance and try again.")
        reply = json.loads(message["content"])
    except QuestionGenerationError:
        raise
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise QuestionGenerationError("OpenAI returned an incomplete response. Try generating again.") from error
    if choice.get("finish_reason") == "length":
        raise QuestionGenerationError("The question set was too long to finish. Generate fewer questions at a time.")
    return _validate_questions(activity, reply.get("questions") if isinstance(reply, dict) else None, count)
