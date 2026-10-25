# Modulus Edu — Coaching Management System

Modulus Edu is a Django-based coaching management application with role-based access for Super Admins, Teachers, and Students. It provides centralized management of students, attendance, class schedules, examinations, results, educational resources, and notifications.

## Features

### 1. Super Admin Dashboard
- Manage student accounts and teacher accounts.
- Create, edit, and manage weekly class schedules.
- Record student and teacher attendance.
- Monitor monthly teacher activity, classes, and examinations.
- Manage examinations, student marks, and academic records.
- Review student feedback.
- Manage SMS settings and notification reports.

### 2. Teacher Dashboard
- View student information and assigned classes.
- View weekly schedules and attendance records.
- Submit attendance requests for scheduled classes.
- Track monthly classes, examinations, and teaching activity.
- Upload educational resources for students.

### 3. Student Dashboard
- View class schedules and upcoming examinations.
- Access examination results, marks, and attendance records.
- Track academic progress and subject-wise performance.
- Access class sheets, books, and educational resources.
- Submit feedback to the administration.
- Create original AI-generated CQ and MCQ practice for a selected subject, paper, chapter, and topic.
- Get separate AI-prioritized topic lists for CQ and MCQ preparation from a selected chapter.
- Save practice sets and track questions as practiced or needing help.

### 4. Class and Academic Management
- Organize students by HSC first-year and second-year batches.
- Manage weekly schedules and completed class records.
- Organize examinations by academic year, subject, paper, and chapter.
- Record and update examination marks.
- View teacher activity and examination statistics by month.

### 5. Attendance and Notifications
- Record student attendance as present, absent, or late.
- Manage teacher attendance with administrative verification.
- Send attendance notifications through WhatsApp Cloud API.
- Send attendance-related and examination-result SMS notifications through BulkSMSBD.
- Track notification attempts, provider responses, and errors.
- Enable or disable SMS notifications from the Super Admin dashboard.

### 6. Educational Resources
- Upload PDF files, Office documents, and images.
- Restrict access to resources according to student batches.
- Allow authenticated students to access their educational materials.
- Support external book links.

### 7. User Interface
- Separate, login-protected dashboards for each user role.
- Responsive interface with light and dark themes.
- Persistent theme preferences within the same browser.
- Modulus Edu branding across dashboards and login pages.

## Technology Stack

- **Backend:** Python, Django
- **Database:** SQLite or MySQL
- **Frontend:** HTML, CSS, JavaScript, and Tailwind CSS
- **Integrations:** Gemini API, OpenAI (legacy planner), WhatsApp Cloud API, BulkSMSBD
- **Deployment:** cPanel with Python Passenger

## Getting Started

### Prerequisites
- Python and pip
- A virtual environment
- Git (optional)

### Installation

Run the following commands from the project directory containing `manage.py`.

**Windows PowerShell**

```powershell
# Activate your virtual environment
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Apply database migrations
python manage.py migrate

# Create a Super Admin account
python manage.py createsuperuser

# Start the development server
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

If your virtual environment has a different name, replace `venv` with the appropriate directory.

## Environment Configuration

Create a local `.env` file from `.env.example` if one is provided:

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

Configure the required environment variables for your environment, including:

- Django secret key and allowed hosts
- Database connection settings
- WhatsApp Cloud API access token and phone number ID
- BulkSMSBD API key and sender ID
- Gemini API key for original AI-generated topic practice questions
- OpenAI API key for the archived weekly planner, if you continue using it

Keep credentials out of source control. The `.env` file should remain excluded through `.gitignore`. For production, use securely configured hosting environment variables or an appropriately protected configuration file.

## AI Topic Practice

Apply the topic practice database changes with:

```powershell
python manage.py migrate
```

The topic practice feature reads `GEMINI_API_KEY` and `GEMINI_MODEL` (default `gemini-2.5-flash`) to generate original CQ, MCQ, knowledge (ক), and understanding (খ) practice through the Gemini API. No web search is used. Students select the subject, paper, chapter, topic, and question type. Practice sets and each question's progress are saved. A separate chapter guide returns only prioritized topic names for CQ and MCQ; it does not generate questions.

Generated questions are original practice content based on the student's selected subject, paper, chapter, and topic; the feature does not perform web search and cannot guarantee that answers are error-free. Check generated answers against textbooks or a teacher. The chapter guide prioritizes topics using syllabus context and common exam patterns; it is not a verified frequency analysis of a specific past-paper dataset and does not claim that any topic appeared in a specific exam. The practice feature does not reproduce past board questions verbatim. Missing Gemini credentials and provider failures are shown to the student; there is no rule-based question fallback. The former weekly planner and its saved records remain archived at `/student/study-planner/legacy/` and are not deleted. Never put provider credentials in frontend code or commit `.env`.

## WhatsApp Configuration

WhatsApp notifications require valid Meta WhatsApp Cloud API credentials, approved message templates, and recipient consent.

Configure the approved `present_notice` and `absent_notice` Utility templates in Meta WhatsApp Manager. The integration supports attendance notifications for present and absent statuses. Late-status WhatsApp notifications are not currently supported.

API acceptance does not guarantee delivery or read status. Delivery tracking requires a configured Meta webhook.

To retry failed attendance notifications:

```powershell
python manage.py retry_whatsapp_attendance
```

## BulkSMSBD Configuration

Configure your BulkSMSBD API key and registered sender ID in the environment settings.

The sender ID must be enabled for your BulkSMSBD account. Account-side sender configuration errors must be resolved with the provider.

The application supports attendance and examination-result SMS notifications, SMS reporting, balance checks, and a global SMS enable/disable setting.

## Production Deployment

For cPanel deployment instructions covering Python Passenger, production environment variables, database configuration, static files, and safe data migration, see [`CPANEL_DEPLOYMENT.md`](CPANEL_DEPLOYMENT.md).

Before deployment, configure production settings, disable Django debug mode, protect all credentials, and verify database and static-file configuration.

## Testing

Run the project's automated tests with:

```powershell
python manage.py test students attendance exams portal
```
