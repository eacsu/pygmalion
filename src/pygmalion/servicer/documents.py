"""共享文档服务，不占用机器控制权。"""

from ..documents import repository
from .public_errors import PublicError


def get(identifier):
    try:
        return repository.get(identifier)
    except repository.Missing as exc:
        raise PublicError(404, "document_not_found", "文档不存在") from exc


def update(identifier, document, etag):
    if etag is None:
        raise PublicError(428, "precondition_required", "保存文档需要 If-Match 版本")
    try:
        revision = int(etag.strip('"'))
    except ValueError as exc:
        raise PublicError(422, "invalid_document_revision", "文档版本不正确") from exc
    try:
        return repository.update(identifier, document.model_dump(mode="json"), revision)
    except repository.Missing as exc:
        raise PublicError(404, "document_not_found", "文档不存在") from exc
    except repository.Conflict as exc:
        raise PublicError(
            412,
            "document_changed",
            "文档已被其他客户端修改；请另存本页修改或读取服务端版本",
            advice="refresh",
        ) from exc


def create(document, key):
    return repository.create(document.model_dump(mode="json"), key)


def list_documents(limit):
    return repository.list_documents(limit)
