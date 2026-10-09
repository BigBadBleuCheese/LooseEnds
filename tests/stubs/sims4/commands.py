registered = {}


class CommandType:
    Live = 'Live'


def Command(name, command_type=None):
    def decorator(function):
        registered[name] = function
        return function
    return decorator


class CheatOutput:
    lines = []

    def __init__(self, connection):
        pass

    def __call__(self, text):
        CheatOutput.lines.append(text)
