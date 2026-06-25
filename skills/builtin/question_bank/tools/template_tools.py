# skills/builtin/question_bank/tools/template_tools.py


class TemplateTools:

    def __init__(self, template_manager=None, question_store=None):
        self._tm = template_manager
        self._store = question_store

    def list(self) -> list:
        return self._tm.list_templates()

    def apply(self, template_name: str) -> dict:
        return self._tm.apply_template(template_name)

    def import_template(self, file_path: str) -> dict:
        return self._tm.import_template(file_path)

    def create(self, name: str, subjects: list[dict]) -> dict:
        return self._tm.create_template(name, subjects)

    def export(self, template_name: str, output_path: str) -> dict:
        success = self._tm.export_template(template_name, output_path)
        return {"success": success}

    def delete(self, template_name: str) -> dict:
        success = self._tm.delete_template(template_name)
        return {"success": success}

    def get_active(self) -> list:
        return self._tm.get_active_subjects()

    def get_subject_by_code(self, code: str) -> dict:
        return self._tm.get_subject_by_code(code) or {}

    def get_question_types(self) -> list:
        return self._tm.get_question_types()
