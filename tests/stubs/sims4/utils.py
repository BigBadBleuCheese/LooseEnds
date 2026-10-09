import functools


class flexmethod:
    __slots__ = ('__wrapped_method__',)

    def __init__(self, method):
        self.__wrapped_method__ = method

    def __get__(self, instance, owner):
        return functools.partial(self.__wrapped_method__, owner, instance)
