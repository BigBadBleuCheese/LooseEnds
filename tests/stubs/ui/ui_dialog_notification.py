shown = []


class _Dialog:
    def __init__(self, owner, title, text):
        self.owner, self.title, self.text = owner, title, text

    def show_dialog(self):
        shown.append((self.title(), self.text()))


class _Factory:
    def default(self, owner, title=None, text=None, **kwargs):
        return _Dialog(owner, title, text)


class UiDialogNotification:
    @staticmethod
    def TunableFactory():
        return _Factory()
