from django.apps import AppConfig


class RecipesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recipes'

    def ready(self):
        """Enable SQLite WAL mode on every new DB connection.

        WAL (Write-Ahead Logging) allows concurrent reads with one writer,
        preventing 'database is locked' errors with multiple Gunicorn workers.
        """
        from django.db.backends.signals import connection_created

        def set_wal_mode(sender, connection, **kwargs):
            if connection.vendor == 'sqlite':
                connection.cursor().execute('PRAGMA journal_mode=WAL;')
                connection.cursor().execute('PRAGMA synchronous=NORMAL;')

        connection_created.connect(set_wal_mode)
