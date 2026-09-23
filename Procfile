release: python manage.py migrate --noinput && python manage.py sync_quickword_ipa
web: gunicorn -c gunicorn.conf.py config.wsgi:application
