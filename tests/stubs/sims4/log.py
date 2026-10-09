import traceback
records = []


class Logger:
    def __init__(self, name, default_owner=None):
        self.name = name

    def _log(self, level, message, *args, **kwargs):
        records.append((level, message.format(*args) if args else message))

    def info(self, message, *args, **kwargs):
        self._log('info', message, *args)

    def warn(self, message, *args, **kwargs):
        self._log('warn', message, *args)

    def error(self, message, *args, **kwargs):
        self._log('error', message, *args)

    def exception(self, message, *args, exc=None, **kwargs):
        self._log('exception', message, *args)
