"""GLM company/employee profile tagging."""
from ._common import load_catalog, model_tags, object_input


class ProfileTagger:
    def __init__(self, *, catalog_path=None, transport=None):
        self.catalog = load_catalog(catalog_path)
        self.transport = transport

    def tag(self, data):
        """Input/output: city, text; output additionally contains catalogue tag codes."""
        profile = object_input(data, {'city': 200, 'text': 30000})
        tags = model_tags('LLM_MODEL_CONTEXT',
            'Определи интересы компании или сотрудника из описания деятельности и должности. '
            'Выбери город и его регион из справочника, а также обоснованные отраслевые и '
            'деловые теги. При неоднозначном или неизвестном городе не угадывай географию. '
            'Поле city задаёт местонахождение клиента; упомянутый в тексте город поставщика '
            'или заказчика сам по себе не означает регион работы клиента. '
            'Для сотрудника учти указанную должность и деятельность компании; '
            'не добавляй всем сотрудникам одинаковые темы управления, налогов и найма. '
            'Не делай выводов о деятельности только из названия компании.',
            {'profile': profile}, self.catalog, self.transport)
        return {**profile, 'tags': tags}
