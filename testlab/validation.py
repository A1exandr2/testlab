"""Проверка полей формы."""

NAMES = {
    'name': 'Имя или название',
    'email': 'Электронная почта',
    'password': 'Пароль',
    'title': 'Название проверки',
    'steps': 'Шаги проверки',
    'expected': 'Ожидаемый результат',
    'actual': 'Комментарий',
}


class RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text(data, key, limit=200, required=True):
    value = data.get(key, '')
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (required and not value.strip())
    ):
        raise ValueError(
            f'Проверьте поле «{NAMES.get(key, key)}» (до {limit} символов)'
        )
    return value.strip()


def ident(data, key):
    value = data.get(key)
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError('Выберите группу или проверку')
    return int(value)
