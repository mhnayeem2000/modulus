import io
import json
import os
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from google.genai.errors import APIError

from .models import (
    TopicPracticeQuestion,
    TopicPracticeSession,
    UserProfile,
)
from .topic_practice import (
    CQ_INITIAL_COUNT,
    CQ_MORE_COUNT,
    KHO_INITIAL_COUNT,
    KHO_MORE_COUNT,
    KO_INITIAL_COUNT,
    KO_MORE_COUNT,
    MCQ_INITIAL_COUNT,
    MCQ_MORE_COUNT,
    TopicPracticeError,
    _generate_original_questions,
    generate_topic_recommendations,
)
from students.models import Student


class TopicPracticeTests(TestCase):
    def setUp(self):
        self.student_user = get_user_model().objects.create_user(
            username='topic-practice-student',
            password='safe-test-password',
        )
        UserProfile.objects.create(
            user=self.student_user,
            role=UserProfile.Role.STUDENT,
        )
        self.student = Student.objects.create(
            user=self.student_user,
            name='Practice Student',
            student_id='TP-1001',
            class_name='HSC Science',
            year_group='first',
        )
        self.client.force_login(self.student_user)

    @staticmethod
    def questions(count, question_type='cq'):
        return [
            {
                'prompt': f'Original {question_type} prompt {index}',
                'choices': (
                    [f'Option {index}-{choice}' for choice in range(4)]
                    if question_type == 'mcq' else []
                ),
                'answer': f'Answer {index}',
                'explanation': f'Explanation {index}',
            }
            for index in range(count)
        ]

    def valid_payload(self, question_type='cq'):
        return {
            'subject': 'পদার্থবিজ্ঞান',
            'paper': '১ম পত্র',
            'chapter': 'ভেক্টর',
            'topic': 'ভেক্টরের যোগ',
            'question_type': question_type,
        }

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_practice_page_shows_topic_selection_and_saved_history(self, generate):
        response = self.client.get(reverse('student_study_planner'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'বিষয়, paper, chapter ও topic')
        self.assertContains(response, 'ক — জ্ঞানমূলক')
        self.assertContains(response, 'খ — অনুধাবনমূলক')
        self.assertContains(response, 'এই chapter-এ কোন topic আগে পড়বে?')
        self.assertContains(response, 'নির্দিষ্ট past-paper dataset')
        self.assertContains(response, 'দিন বা বিষয় অনুযায়ী আগের practice')
        generate.assert_not_called()

    @patch('portal.topic_practice_views.generate_topic_recommendations')
    def test_chapter_recommendations_return_topic_names_for_cq_and_mcq(self, recommend):
        recommend.return_value = {
            'cq_topics': ['ভেক্টরের উপাংশ', 'সাম্যাবস্থা'],
            'mcq_topics': ['একক ভেক্টর', 'লব্ধি নির্ণয়'],
        }

        response = self.client.post(
            reverse('recommend_chapter_topics'),
            {
                'subject': 'পদার্থবিজ্ঞান',
                'paper': '১ম পত্র',
                'chapter': 'ভেক্টর',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('ভেক্টরের উপাংশ', data['html'])
        self.assertIn('লব্ধি নির্ণয়', data['html'])
        self.assertIn('CQ-এর জন্য', data['html'])
        self.assertIn('MCQ-এর জন্য', data['html'])
        self.assertNotIn('উত্তর:', data['html'])
        recommend.assert_called_once_with('পদার্থবিজ্ঞান', '১ম পত্র', 'ভেক্টর')

    @patch('portal.topic_practice_views.generate_topic_recommendations')
    def test_chapter_recommendations_reject_chapter_outside_selected_paper(self, recommend):
        response = self.client.post(
            reverse('recommend_chapter_topics'),
            {
                'subject': 'পদার্থবিজ্ঞান',
                'paper': '১ম পত্র',
                'chapter': 'অস্তিত্বহীন অধ্যায়',
            },
        )

        self.assertEqual(response.status_code, 400)
        recommend.assert_not_called()

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_create_cq_practice_saves_configured_original_questions(self, generate):
        generate.return_value = self.questions(CQ_INITIAL_COUNT)

        response = self.client.post(
            reverse('create_topic_practice'),
            self.valid_payload('cq'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn(f'{CQ_INITIAL_COUNT}টি', data['message'])
        session = TopicPracticeSession.objects.get(student=self.student)
        self.assertEqual(session.question_type, TopicPracticeSession.QuestionType.CQ)
        self.assertEqual(session.sources, [])
        self.assertEqual(session.questions.count(), CQ_INITIAL_COUNT)
        generate.assert_called_once_with(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'cq',
            CQ_INITIAL_COUNT,
        )
        self.assertIn('Original cq prompt 0', data['html'])

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_create_mcq_practice_saves_twenty_mcqs_with_four_choices(self, generate):
        generate.return_value = self.questions(MCQ_INITIAL_COUNT, 'mcq')

        response = self.client.post(
            reverse('create_topic_practice'),
            self.valid_payload('mcq'),
        )

        self.assertEqual(response.status_code, 200)
        session = TopicPracticeSession.objects.get(student=self.student)
        self.assertEqual(session.question_type, TopicPracticeSession.QuestionType.MCQ)
        self.assertEqual(session.questions.count(), MCQ_INITIAL_COUNT)
        self.assertTrue(all(
            len(question.choices) == 4
            for question in session.questions.all()
        ))
        generate.assert_called_once_with(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'mcq',
            MCQ_INITIAL_COUNT,
        )

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_create_knowledge_practice_saves_questions(self, generate):
        generate.return_value = self.questions(KO_INITIAL_COUNT, 'ko')

        response = self.client.post(
            reverse('create_topic_practice'),
            self.valid_payload('ko'),
        )

        self.assertEqual(response.status_code, 200)
        session = TopicPracticeSession.objects.get(student=self.student)
        self.assertEqual(session.question_type, TopicPracticeSession.QuestionType.KO)
        self.assertEqual(session.questions.count(), KO_INITIAL_COUNT)
        generate.assert_called_once_with(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'ko',
            KO_INITIAL_COUNT,
        )

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_create_understanding_practice_saves_questions(self, generate):
        generate.return_value = self.questions(KHO_INITIAL_COUNT, 'kho')

        response = self.client.post(
            reverse('create_topic_practice'),
            self.valid_payload('kho'),
        )

        self.assertEqual(response.status_code, 200)
        session = TopicPracticeSession.objects.get(student=self.student)
        self.assertEqual(session.question_type, TopicPracticeSession.QuestionType.KHO)
        self.assertEqual(session.questions.count(), KHO_INITIAL_COUNT)
        generate.assert_called_once_with(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'kho',
            KHO_INITIAL_COUNT,
        )

    @patch.dict(os.environ, {'GEMINI_API_KEY': ''})
    def test_create_practice_without_gemini_key_returns_json_error_without_saving(self):
        response = self.client.post(
            reverse('create_topic_practice'),
            self.valid_payload('cq'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 503)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('GEMINI_API_KEY', data['error'])
        self.assertFalse(TopicPracticeSession.objects.filter(student=self.student).exists())

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_load_more_appends_configured_cq_questions_without_losing_progress(self, generate):
        session = TopicPracticeSession.objects.create(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টরের যোগ',
            question_type=TopicPracticeSession.QuestionType.CQ,
        )
        original = TopicPracticeQuestion.objects.create(
            session=session,
            sequence=1,
            prompt='Already saved',
            status=TopicPracticeQuestion.Status.PRACTICED,
        )
        generate.return_value = self.questions(CQ_MORE_COUNT)

        response = self.client.post(
            reverse('load_more_topic_practice', args=[session.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.questions.count(), CQ_MORE_COUNT + 1)
        original.refresh_from_db()
        self.assertEqual(original.status, TopicPracticeQuestion.Status.PRACTICED)
        self.assertEqual(
            list(session.questions.order_by('sequence').values_list('sequence', flat=True)),
            list(range(1, CQ_MORE_COUNT + 2)),
        )
        generate.assert_called_once_with(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'cq',
            CQ_MORE_COUNT,
        )

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_load_more_appends_twenty_mcqs(self, generate):
        session = TopicPracticeSession.objects.create(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টরের যোগ',
            question_type=TopicPracticeSession.QuestionType.MCQ,
        )
        generate.return_value = self.questions(MCQ_MORE_COUNT, 'mcq')

        response = self.client.post(
            reverse('load_more_topic_practice', args=[session.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.questions.count(), MCQ_MORE_COUNT)
        self.assertEqual(
            json.loads(response.content)['question_count'],
            MCQ_MORE_COUNT,
        )

    @patch('portal.topic_practice_views.generate_topic_practice')
    def test_load_more_supports_knowledge_and_understanding_types(self, generate):
        for question_type, batch_count in (
            (TopicPracticeSession.QuestionType.KO, KO_MORE_COUNT),
            (TopicPracticeSession.QuestionType.KHO, KHO_MORE_COUNT),
        ):
            with self.subTest(question_type=question_type):
                session = TopicPracticeSession.objects.create(
                    student=self.student,
                    subject='পদার্থবিজ্ঞান',
                    paper='১ম পত্র',
                    chapter='ভেক্টর',
                    topic='ভেক্টরের যোগ',
                    question_type=question_type,
                )
                generate.return_value = self.questions(batch_count, question_type)

                response = self.client.post(
                    reverse('load_more_topic_practice', args=[session.pk]),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(session.questions.count(), batch_count)
                generate.assert_called_with(
                    'পদার্থবিজ্ঞান',
                    '১ম পত্র',
                    'ভেক্টর',
                    'ভেক্টরের যোগ',
                    question_type,
                    batch_count,
                )
                generate.reset_mock()

    def test_question_status_is_saved_and_history_can_filter_by_subject(self):
        session = TopicPracticeSession.objects.create(
            student=self.student,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টরের যোগ',
            question_type=TopicPracticeSession.QuestionType.CQ,
        )
        question = TopicPracticeQuestion.objects.create(
            session=session,
            sequence=1,
            prompt='Practice this',
        )
        other_session = TopicPracticeSession.objects.create(
            student=self.student,
            subject='রসায়ন',
            paper='১ম পত্র',
            chapter='গুণগত রসায়ন',
            topic='পরীক্ষা',
            question_type=TopicPracticeSession.QuestionType.MCQ,
        )

        response = self.client.post(
            reverse('update_topic_practice_status', args=[question.pk]),
            {'status': TopicPracticeQuestion.Status.NEEDS_HELP},
        )

        self.assertEqual(response.status_code, 200)
        question.refresh_from_db()
        self.assertEqual(question.status, TopicPracticeQuestion.Status.NEEDS_HELP)
        history = self.client.get(reverse('student_study_planner'), {
            'subject': 'পদার্থবিজ্ঞান',
        })
        listed_sessions = list(history.context['session_page'].object_list)
        self.assertEqual([item.pk for item in listed_sessions], [session.pk])
        self.assertNotIn(other_session, listed_sessions)

    def test_students_cannot_update_questions_from_another_student(self):
        other_student = Student.objects.create(
            name='Other Practice Student',
            student_id='TP-1002',
            class_name='HSC Science',
            year_group='first',
        )
        session = TopicPracticeSession.objects.create(
            student=other_student,
            subject='পদার্থবিজ্ঞান',
            paper='১ম পত্র',
            chapter='ভেক্টর',
            topic='ভেক্টরের যোগ',
            question_type=TopicPracticeSession.QuestionType.CQ,
        )
        question = TopicPracticeQuestion.objects.create(
            session=session,
            sequence=1,
            prompt='Private question',
        )

        response = self.client.post(
            reverse('update_topic_practice_status', args=[question.pk]),
            {'status': TopicPracticeQuestion.Status.PRACTICED},
        )

        self.assertEqual(response.status_code, 404)

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': ''})
    def test_original_question_generation_requires_gemini_credentials(self, client_factory):
        with self.assertRaisesMessage(TopicPracticeError, 'GEMINI_API_KEY'):
            _generate_original_questions(
                'পদার্থবিজ্ঞান',
                '১ম পত্র',
                'ভেক্টর',
                'যোগ',
                'cq',
                1,
            )
        client_factory.assert_not_called()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_model_error_is_reported(self, client_factory):
        client = MagicMock()
        client.models.generate_content.side_effect = APIError(
            404,
            {'error': {'message': 'Model was not found.'}},
        )
        client_factory.return_value = client

        with self.assertRaisesMessage(TopicPracticeError, 'Gemini API-তে model পাওয়া যায়নি'):
            _generate_original_questions(
                'পদার্থবিজ্ঞান',
                '১ম পত্র',
                'ভেক্টর',
                'যোগ',
                'cq',
                1,
            )

        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_quota_error_is_reported(self, client_factory):
        client = MagicMock()
        client.models.generate_content.side_effect = APIError(
            429,
            {'error': {'message': 'Rate limit exceeded.'}},
        )
        client_factory.return_value = client

        with self.assertRaisesMessage(TopicPracticeError, 'Gemini API rate limit বা quota শেষ'):
            _generate_original_questions(
                'পদার্থবিজ্ঞান',
                '১ম পত্র',
                'ভেক্টর',
                'যোগ',
                'cq',
                1,
            )
        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_sdk_uses_configured_key_model_and_exam_prompt(self, client_factory):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps({
            'questions': [{
                'prompt': 'Original question',
                'choices': [],
                'answer': 'Answer outline',
            }],
        })
        client_factory.return_value = client

        questions = _generate_original_questions(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'cq',
            1,
        )

        self.assertEqual(questions[0]['prompt'], 'Original question')
        self.assertEqual(questions[0]['explanation'], '')
        client_factory.assert_called_once_with(api_key='test-gemini-key')
        client.models.generate_content.assert_called_once()
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call['model'], 'gemini-2.5-flash')
        self.assertEqual(json.loads(call['contents'])['topic'], 'ভেক্টরের যোগ')
        self.assertEqual(call['config'].response_mime_type, 'application/json')
        schema = call['config'].response_schema
        self.assertEqual(schema.required, ['questions'])
        question_schema = schema.properties['questions'].items
        self.assertEqual(
            question_schema.required,
            ['prompt', 'choices', 'answer', 'explanation'],
        )
        self.assertIn('choices', question_schema.properties)
        self.assertEqual(call['config'].temperature, 0.7)
        system_prompt = call['config'].system_instruction
        self.assertIn('Do not use web search', system_prompt)
        self.assertIn('board-exam-style', system_prompt)
        self.assertIn('উদ্দীপক', system_prompt)
        self.assertIn('ক), খ), গ), ঘ)', system_prompt)
        self.assertIn('one or two short sentences', system_prompt)
        self.assertIn('This question assesses...', system_prompt)
        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_knowledge_and_understanding_prompts_are_distinct(self, client_factory):
        for question_type, expected_prompt in (
            ('ko', 'জ্ঞানমূলক (ক)'),
            ('kho', 'অনুধাবনমূলক (খ)'),
        ):
            with self.subTest(question_type=question_type):
                client = MagicMock()
                client.models.generate_content.return_value.text = json.dumps({
                    'questions': [{
                        'prompt': 'Topic question',
                        'choices': [],
                        'answer': 'Correct answer',
                        'explanation': '',
                    }],
                })
                client_factory.return_value = client

                _generate_original_questions(
                    'পদার্থবিজ্ঞান',
                    '১ম পত্র',
                    'ভেক্টর',
                    'ভেক্টরের যোগ',
                    question_type,
                    1,
                )

                system_prompt = (
                    client.models.generate_content.call_args.kwargs['config']
                    .system_instruction
                )
                self.assertIn(expected_prompt, system_prompt)
                client.close.assert_called_once()
                client_factory.reset_mock()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_mcq_response_requires_four_nonempty_options(self, client_factory):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps({
            'questions': [{
                'prompt': 'Which one is correct?',
                'choices': ['A', 'B', 'C', 'D'],
                'answer': 'A',
                'explanation': 'Reason',
            }],
        })
        client_factory.return_value = client

        questions = _generate_original_questions(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
            'ভেক্টরের যোগ',
            'mcq',
            1,
        )

        self.assertEqual(questions[0]['choices'], ['A', 'B', 'C', 'D'])
        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_safety_block_has_actionable_error(self, client_factory):
        client = MagicMock()
        response = client.models.generate_content.return_value
        response.text = None
        response.candidates = [MagicMock(finish_reason='SAFETY')]
        client_factory.return_value = client

        with self.assertRaisesMessage(TopicPracticeError, 'নিরাপত্তাজনিত কারণে'):
            _generate_original_questions(
                'পদার্থবিজ্ঞান',
                '১ম পত্র',
                'ভেক্টর',
                'ভেক্টরের যোগ',
                'cq',
                1,
            )
        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_topic_recommendations_return_only_topic_names(self, client_factory):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps({
            'cq_topics': ['ভেক্টরের উপাংশ', 'ভেক্টরের উপাংশ', 'সাম্যাবস্থা'],
            'mcq_topics': ['একক ভেক্টর', 'লব্ধি নির্ণয়'],
        })
        client_factory.return_value = client

        recommendations = generate_topic_recommendations(
            'পদার্থবিজ্ঞান',
            '১ম পত্র',
            'ভেক্টর',
        )

        self.assertEqual(
            recommendations,
            {
                'cq_topics': ['ভেক্টরের উপাংশ', 'সাম্যাবস্থা'],
                'mcq_topics': ['একক ভেক্টর', 'লব্ধি নির্ণয়'],
            },
        )
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call['model'], 'gemini-2.5-flash')
        self.assertEqual(
            json.loads(call['contents']),
            {
                'subject': 'পদার্থবিজ্ঞান',
                'paper': '১ম পত্র',
                'chapter': 'ভেক্টর',
            },
        )
        schema = call['config'].response_schema
        self.assertEqual(schema.required, ['cq_topics', 'mcq_topics'])
        self.assertIn('Do not generate questions', call['config'].system_instruction)
        self.assertIn('no past-paper dataset is supplied', call['config'].system_instruction)
        client.close.assert_called_once()

    @patch('portal.topic_practice.genai.Client')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test-gemini-key'})
    def test_gemini_topic_recommendations_reject_invalid_response(self, client_factory):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps({
            'cq_topics': ['ভেক্টরের উপাংশ'],
            'mcq_topics': [],
        })
        client_factory.return_value = client

        with self.assertRaisesMessage(TopicPracticeError, 'topic suggestion যাচাই করা যায়নি'):
            generate_topic_recommendations('পদার্থবিজ্ঞান', '১ম পত্র', 'ভেক্টর')

        client.close.assert_called_once()
