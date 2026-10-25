import json
import logging
import os

from google import genai
from google.genai import types
from google.genai.errors import APIError


logger = logging.getLogger(__name__)
CQ_INITIAL_COUNT = 1
MCQ_INITIAL_COUNT = 2
CQ_MORE_COUNT = 1
MCQ_MORE_COUNT = 2
KO_INITIAL_COUNT = 5
KHO_INITIAL_COUNT = 5
KO_MORE_COUNT = 5
KHO_MORE_COUNT = 5


class TopicPracticeError(Exception):
    pass


def _gemini_api_error_message(status_code):
    if status_code in (401, 403):
        return 'Gemini API key বা project permission যাচাই করুন।'
    if status_code == 404:
        return (
            'Gemini API-তে model পাওয়া যায়নি। GEMINI_MODEL ও API key-এর project access '
            'যাচাই করুন।'
        )
    if status_code == 429:
        return 'Gemini API rate limit বা quota শেষ হয়েছে। Gemini API usage ও limits যাচাই করুন।'
    if status_code >= 500:
        return 'Gemini service-এ সাময়িক সমস্যা হচ্ছে। কিছুক্ষণ পর আবার চেষ্টা করুন।'
    return f'Gemini request ব্যর্থ হয়েছে (HTTP {status_code})। API configuration যাচাই করুন।'


def _generate_original_questions(subject, paper, chapter, topic, question_type, count):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise TopicPracticeError(
            'AI question generation চালু করতে server environment-এ GEMINI_API_KEY সেট করতে হবে।'
        )
    model = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip() or 'gemini-2.5-flash'
    is_mcq = question_type == 'mcq'
    question_format = {
        'cq': (
            'প্রতিটি CQ-তে একটি উদ্দীপক এবং ক), খ), গ), ঘ) ক্রমান্বয়ে জ্ঞান, অনুধাবন, '
            'প্রয়োগ ও উচ্চতর দক্ষতার অংশ থাকবে। উত্তরে চার অংশের সঠিক সমাধান দাও। '
            'choices খালি list হবে।'
        ),
        'mcq': (
            'প্রতিটি MCQ-তে ঠিক চারটি choices, answer-এ সঠিক option-এর পুরো text, '
            'এবং সংক্ষিপ্ত explanation দাও।'
        ),
        'ko': (
            'প্রতিটি প্রশ্ন আলাদা জ্ঞানমূলক (ক) প্রশ্ন হবে: গুরুত্বপূর্ণ সংজ্ঞা, সূত্র, '
            'একক, তথ্য বা মৌলিক ধারণা যাচাই করবে। উত্তর সংক্ষিপ্ত ও সরাসরি হবে। choices খালি list হবে।'
        ),
        'kho': (
            'প্রতিটি প্রশ্ন আলাদা অনুধাবনমূলক (খ) প্রশ্ন হবে: গুরুত্বপূর্ণ ধারণা কেন বা কীভাবে '
            'ঘটে তা ব্যাখ্যা করতে হবে। উত্তর যুক্তিসহ সংক্ষিপ্তভাবে ব্যাখ্যা করবে। choices খালি list হবে।'
        ),
    }[question_type]
    system_instruction = (
        'You create accurate, original Bangladesh HSC board-exam-style practice '
        'questions in natural Bengali. '
        'Use the exact subject, paper, chapter and topic supplied by the student. '
        'Do not use web search or invent citations. Never copy, quote, or claim to '
        'reproduce a past-board question, and do not claim to know exact past-year '
        'questions. Prioritize high-yield syllabus concepts and common Bangladesh HSC '
        'board-exam patterns. Create original questions and do not label them as verified '
        'past-board questions. '
        'Before returning each answer, independently re-check its syllabus fit, facts, '
        'formulas, calculations, units, answer and explanation. Ensure every MCQ has '
        'exactly one correct option. If a fact or answer cannot be established confidently, '
        'do not invent it. Keep each explanation concise (normally one or two short '
        'sentences) and focused only on the topic-specific reasoning that helps the '
        'student understand why the answer is correct. For CQ, put the four part-wise '
        'solutions in answer; do not use explanation to describe what each part assesses, '
        'summarize the question design or learning objectives, repeat the answer, or add '
        'generic commentary such as "This question assesses...". '
        'For CQ, write one concise stimulus (উদ্দীপক) followed by four linked parts '
        'labelled ক), খ), গ), ঘ), progressing from knowledge and understanding to '
        'application and higher-order reasoning. Keep the stimulus and all four parts '
        'specific to the selected topic. For standalone ক/খ question types, return only '
        'the requested short-question style, not a full CQ. For MCQ, write an exam-style '
        'conceptual or calculation stem with four plausible options and exactly one '
        'correct answer. Return only valid JSON with one key '
        '"questions", containing exactly the requested number of objects. '
        f'{question_format} Keep each prompt and answer useful and self-contained.'
    )
    prompt = json.dumps({
        'subject': subject,
        'paper': paper,
        'chapter': chapter,
        'topic': topic,
        'question_type': question_type,
        'count': count,
    }, ensure_ascii=False)
    response_schema = types.Schema(
        type='OBJECT',
        properties={
            'questions': types.Schema(
                type='ARRAY',
                items=types.Schema(
                    type='OBJECT',
                    properties={
                        'prompt': types.Schema(type='STRING'),
                        'choices': types.Schema(
                            type='ARRAY',
                            items=types.Schema(type='STRING'),
                        ),
                        'answer': types.Schema(type='STRING'),
                        'explanation': types.Schema(type='STRING'),
                    },
                    required=['prompt', 'choices', 'answer', 'explanation'],
                ),
            ),
        },
        required=['questions'],
    )
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type='application/json',
                response_schema=response_schema,
                temperature=0.7,
                max_output_tokens=16000,
            ),
        )
    except APIError as exc:
        logger.warning('Gemini topic practice request failed with HTTP %s.', exc.code)
        raise TopicPracticeError(_gemini_api_error_message(exc.code)) from exc
    finally:
        client.close()
    try:
        payload = json.loads(response.text or '')
        raw_questions = payload['questions']
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        finish_reason = ''
        try:
            finish_reason = response.candidates[0].finish_reason
            finish_reason = getattr(finish_reason, 'name', finish_reason)
        except (AttributeError, IndexError, TypeError):
            pass
        logger.warning(
            'Gemini topic practice returned an invalid response shape (finish reason: %s).',
            finish_reason or 'unknown',
        )
        if finish_reason == 'MAX_TOKENS':
            raise TopicPracticeError(
                'Gemini-এর উত্তরটি নির্ধারিত সীমার চেয়ে বড় হয়েছে। কম প্রশ্ন নিয়ে আবার চেষ্টা করুন।'
            ) from exc
        if finish_reason == 'SAFETY':
            raise TopicPracticeError(
                'Gemini নিরাপত্তাজনিত কারণে উত্তরটি তৈরি করেনি। Topic wording বদলে আবার চেষ্টা করুন।'
            ) from exc
        raise TopicPracticeError('Gemini-এর উত্তরটি যাচাই করা যায়নি। আবার চেষ্টা করুন।') from exc
    if not isinstance(raw_questions, list) or len(raw_questions) != count:
        logger.warning('AI topic practice returned an unexpected question count.')
        raise TopicPracticeError('AI প্রয়োজনীয় সংখ্যক প্রশ্ন দিতে পারেনি। আবার চেষ্টা করুন।')

    questions = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            logger.warning('Gemini topic practice question %s was not an object.', index)
            raise TopicPracticeError('AI-এর প্রশ্নগুলো যাচাই করা যায়নি। আবার চেষ্টা করুন।')
        prompt = item.get('prompt')
        answer = item.get('answer')
        explanation = item.get('explanation', '')
        if not isinstance(explanation, str):
            explanation = ''
        choices = item.get('choices', [])
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or not isinstance(answer, str)
            or not answer.strip()
        ):
            missing_fields = [
                field for field, value in (('prompt', prompt), ('answer', answer))
                if not isinstance(value, str) or not value.strip()
            ]
            logger.warning(
                'Gemini topic practice question %s missed required fields: %s.',
                index,
                ', '.join(missing_fields),
            )
            raise TopicPracticeError('AI-এর প্রশ্নগুলো অসম্পূর্ণ। আবার চেষ্টা করুন।')
        if is_mcq and (
            not isinstance(choices, list)
            or len(choices) != 4
            or any(not isinstance(choice, str) or not choice.strip() for choice in choices)
        ):
            logger.warning('Gemini topic practice MCQ %s returned invalid choices.', index)
            raise TopicPracticeError('AI-এর MCQ options সঠিক নয়। আবার চেষ্টা করুন।')
        if not is_mcq:
            choices = []
        questions.append({
            'prompt': prompt.strip()[:10000],
            'choices': [choice.strip()[:1000] for choice in choices],
            'answer': answer.strip()[:4000],
            'explanation': explanation.strip()[:4000],
        })
    return questions


def generate_topic_practice(subject, paper, chapter, topic, question_type, count):
    return _generate_original_questions(
        subject,
        paper,
        chapter,
        topic,
        question_type,
        count,
    )


def generate_topic_recommendations(subject, paper, chapter):
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        raise TopicPracticeError(
            'AI topic suggestion চালু করতে server environment-এ GEMINI_API_KEY সেট করতে হবে।'
        )
    model = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip() or 'gemini-2.5-flash'
    system_instruction = (
        'You are an HSC syllabus study-prioritization assistant. Based on the exact '
        'subject, paper, and chapter provided, recommend important syllabus topic names '
        'for CQ preparation and MCQ preparation separately, informed by common Bangladesh '
        'HSC board-exam patterns. Do not generate questions, answers, explanations, '
        'descriptions, citations, or study notes. Return only topic names in Bengali '
        'when suitable, as two JSON arrays named cq_topics and mcq_topics. Put the '
        'highest-priority topics first, avoid duplicates, keep every item a concise topic '
        'name belonging to the selected chapter, and provide up to 8 for each format. '
        'Do not claim these are verified counts or a statistical analysis of specific '
        'past papers; no past-paper dataset is supplied.'
    )
    prompt = json.dumps({
        'subject': subject,
        'paper': paper,
        'chapter': chapter,
    }, ensure_ascii=False)
    response_schema = types.Schema(
        type='OBJECT',
        properties={
            'cq_topics': types.Schema(
                type='ARRAY',
                items=types.Schema(type='STRING'),
            ),
            'mcq_topics': types.Schema(
                type='ARRAY',
                items=types.Schema(type='STRING'),
            ),
        },
        required=['cq_topics', 'mcq_topics'],
    )
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type='application/json',
                response_schema=response_schema,
                temperature=0.4,
                max_output_tokens=2000,
            ),
        )
    except APIError as exc:
        logger.warning('Gemini topic recommendation request failed with HTTP %s.', exc.code)
        raise TopicPracticeError(_gemini_api_error_message(exc.code)) from exc
    finally:
        client.close()

    try:
        payload = json.loads(response.text or '')
        recommendations = {}
        for field in ('cq_topics', 'mcq_topics'):
            raw_topics = payload[field]
            if not isinstance(raw_topics, list) or not raw_topics:
                raise ValueError(f'{field} must be a nonempty list')
            topics = []
            for item in raw_topics:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f'{field} contains an invalid topic')
                topic_name = item.strip()[:160]
                if topic_name not in topics:
                    topics.append(topic_name)
            recommendations[field] = topics[:8]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning('Gemini topic recommendation returned an invalid response shape.')
        raise TopicPracticeError(
            'AI topic suggestion যাচাই করা যায়নি। আবার চেষ্টা করুন।'
        ) from exc
    return recommendations
