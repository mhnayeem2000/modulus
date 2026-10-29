# cPanel deployment

This project runs as a Django WSGI application through cPanel's **Setup Python App** (Passenger). Use Python 3.12 or newer. The app supports cPanel MySQL and SQLite; MySQL is recommended for a live multi-user site.

## 1. Upload the project

Create the application root outside `public_html`, for example:

```text
/home/CPANEL_USER/modulus_app
```

Upload the project source into that directory. Do not upload `.venv`, `.env`, the local `db.sqlite3`, Python cache files, or `staticfiles`; copy a database file only if you are deliberately preserving an SQLite installation. Keep the application root private; the uploaded learning materials and SQLite database must not be directly exposed by Apache.

If you are continuing an existing installation, make a private backup of its database and `media` directory first. Copy uploaded files into the server's private `media` directory, preserving their folder structure. Do not overwrite a live database with a fresh local copy.

## 2. Create the Passenger application

In cPanel, open **Setup Python App**, create an application using Python 3.12 or newer, and set:

- **Application root:** `modulus_app` (the directory above, relative to your home directory)
- **Application URL:** the domain and path where the site should open
- **Application startup file:** `passenger_wsgi.py`
- **Application entry point:** `application`

cPanel creates the Passenger `.htaccess` configuration for the selected URL. Keep that generated file; do not replace it with a generic `.htaccess` containing another account's paths.

## 3. Configure environment variables

Set these in the Python application's **Environment variables** section. Replace example values; do not copy production secrets into source files.

```text
DJANGO_SETTINGS_MODULE=modulus.settings
DEBUG=False
SECRET_KEY=<a-new-long-random-secret>
ALLOWED_HOSTS=example.com,www.example.com
CSRF_TRUSTED_ORIGINS=https://example.com,https://www.example.com
DB_ENGINE=mysql
DB_NAME=CPANEL_PREFIX_database
DB_USER=CPANEL_PREFIX_user
DB_PASSWORD=<database-password>
DB_HOST=localhost
DB_PORT=3306
```

Use the exact MySQL database, user, and host shown by cPanel. Create the database and grant the database user access in **MySQL Database Wizard** first. Set up SSL for the domain before enabling `DEBUG=False`; production settings redirect to HTTPS and mark session/CSRF cookies secure by default. `SECURE_SSL_REDIRECT=False` is available only if the host's HTTPS proxy setup requires it; keep HTTPS enabled.

The WhatsApp and BulkSMSBD variables from `.env.example` can also be configured in cPanel if those integrations are used. Do not upload your local `.env`.

If you configure outgoing email, set `EMAIL_HOST`, `EMAIL_PORT`, and the SMTP credentials in cPanel. Use `EMAIL_USE_TLS=True` for STARTTLS or `EMAIL_USE_SSL=True` for implicit TLS, not both. Production selects Django's SMTP backend; local development continues to print email to the console.

## 4. Install dependencies and prepare the database

Use the virtual-environment activation command displayed by cPanel for the application. In cPanel Terminal, from the application root:

```bash
source /home/CPANEL_USER/virtualenv/modulus_app/3.12/bin/activate
cd /home/CPANEL_USER/modulus_app
python -m pip install -r requirements.txt
python manage.py check --deploy
python manage.py migrate
python manage.py createsuperuser
```

The virtual-environment path varies by account and selected Python version; use cPanel's displayed command rather than copying the example literally.

### Keep existing SQLite data (optional)

For a small, low-write installation, set `DB_ENGINE=sqlite` (or leave it at its default) and place the existing `db.sqlite3` in the private application root. The file and its parent directory must be writable by the application user. Do not use this approach for concurrent/high-write production traffic.

To move existing records to MySQL, create a private fixture on the old installation and transfer it securely:

```bash
python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --output deploy-data.json
```

On cPanel, after setting up MySQL and installing dependencies, run migrations and load the fixture:

```bash
python manage.py migrate
python manage.py loaddata deploy-data.json
```

Keep the fixture private; it contains account data and password hashes. Remove the uploaded fixture after a successful import and keep a secure backup.

## 5. Collect and serve static files

Run this after each deployment that changes CSS, JavaScript, images, or templates:

```bash
python manage.py collectstatic --noinput
```

`STATIC_ROOT` defaults to the private application's `staticfiles` directory. In production, WhiteNoise serves compressed, content-hashed static assets through Django/Passenger, so no manual copy into `public_html` is needed. Run `collectstatic` after each deployment so the optimized assets and their manifest are refreshed. The learning-material downloads remain behind the app's authorization checks in the private `media` directory.

Fee receipts are generated in memory when downloaded; PDF copies are not stored in the database or on disk. Keep the bundled Bengali receipt font and logo in the project `static/fonts` and `static/images` directories.

## 6. Restart and verify

Use **Restart** in cPanel's Python application page, then open the configured HTTPS URL. If Passenger does not restart automatically, touch the application's `tmp/restart.txt` file (create `tmp` if needed):

```bash
mkdir -p tmp
touch tmp/restart.txt
```

Check the login page, a static image/CSS file, an authorized material download, and the superadmin dashboard. The deploy check may warn that HSTS is not enabled for every subdomain or preloaded; only set `SECURE_HSTS_INCLUDE_SUBDOMAINS=True` and `SECURE_HSTS_PRELOAD=True` if every relevant subdomain is HTTPS-only. Review the cPanel application/error log if Passenger reports a startup error.

## Deployment notes

- Never run the production site with `DEBUG=True`, and do not put `.env`, database backups, fixtures, or uploaded materials under `public_html`.
- Make a database and media backup before schema upgrades. Run `migrate` and `collectstatic` after uploading updated code.
- Keep the MySQL credentials, Django secret key, SMS API key, and WhatsApp token in cPanel's environment variables; rotate any credential that was ever exposed.
