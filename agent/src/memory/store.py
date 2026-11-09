"""UC-07 v0 (W8-P1-3): memory store SQLite tách theo user_id + tool memory_read / memory_write.

Quy tắc (docs/uc-07.md):
- user_id LUÔN do harness truyền từ session, LLM/body request không đặt được. Mọi câu SQL lọc user_id.
- Mục sensitive (dị ứng, ăn kiêng, sức khoẻ) bắt buộc có consent còn hiệu lực (DB CHECK + kiểm ở đây).
- visited_city chỉ lưu tên thành phố có trong bảng destinations. Không lưu toạ độ chính xác.
- Hết hạn (mặc định 180 ngày) thì không đọc ra nữa và bị xoá cứng; xoá do người dùng là xoá mềm.
"""

import re
from datetime import datetime, timedelta

from agent.db import repo

KINDS = ("food_like", "food_dislike", "allergy", "dietary", "pace", "interest", "visited_city", "other")
TTL_DAYS = 180
COORD = re.compile(r"-?\d{1,3}\.\d{3,}\s*[,;]\s*-?\d{1,3}\.\d{3,}")  # "16.4698, 107.5786"
COLUMNS = "memory_id, kind, value, sensitivity, source_trip_id, created_at, expires_at"


class MemoryRuleError(ValueError):
    pass


def _check_value(kind, value):
    value = (value or "").strip()
    if kind not in KINDS:
        raise MemoryRuleError(f"kind phải thuộc {KINDS}")
    if not value or len(value) > 200:
        raise MemoryRuleError("value rỗng hoặc dài quá 200 ký tự")
    if COORD.search(value):
        raise MemoryRuleError("không lưu toạ độ chính xác vào bộ nhớ")
    if kind == "visited_city" and not repo.query(
            "SELECT 1 FROM destinations WHERE ? IN (name_vi, name_en, destination_id)", (value,)):
        raise MemoryRuleError("visited_city chỉ lưu tên thành phố có trong dữ liệu")
    return value


def active_consent(user_id):
    rows = repo.query("SELECT consent_id FROM consents WHERE user_id = ? AND scope = 'sensitive_memory' AND granted = 1"
                      " AND revoked_at IS NULL ORDER BY consent_id DESC LIMIT 1", (user_id,))  # fmt: skip
    return rows[0]["consent_id"] if rows else None


def grant_sensitive_consent(user_id):
    """Người dùng đồng ý lưu mục nhạy cảm (tick chọn mục sensitive trên thẻ duyệt). Trả consent_id."""
    return active_consent(user_id) or repo.query(
        "INSERT INTO consents (user_id, scope, granted, decided_at) VALUES (?, 'sensitive_memory', 1, ?) RETURNING consent_id",
        (user_id, repo.now()),
    )[0]["consent_id"]


def revoke_sensitive_consent(user_id):
    """Thu hồi đồng ý → xoá mềm mọi mục sensitive của user."""
    ts = repo.now()
    repo.query("UPDATE consents SET revoked_at = ? WHERE user_id = ? AND scope = 'sensitive_memory' AND revoked_at IS NULL",
               (ts, user_id))  # fmt: skip
    repo.query("UPDATE memory_items SET deleted_at = ? WHERE user_id = ? AND sensitivity = 'sensitive' AND deleted_at IS NULL",
               (ts, user_id))  # fmt: skip


def expire_memory():
    """Job dọn: xoá cứng mục đã hết hạn (mọi user). Gọi mỗi lần đọc, đủ rẻ cho SQLite."""
    repo.query("DELETE FROM memory_items WHERE expires_at <= ?", (repo.now(),))


def memory_write(user_id, kind, value, sensitivity="normal", source_trip_id=None, source_message_id=None):
    """Lưu 1 mục người dùng ĐÃ xác nhận. Trùng (kind, value) còn hiệu lực thì gia hạn, không tạo bản sao."""
    value = _check_value(kind, value)
    if sensitivity not in ("normal", "sensitive"):
        raise MemoryRuleError("sensitivity phải là normal hoặc sensitive")
    consent_id = active_consent(user_id) if sensitivity == "sensitive" else None
    if sensitivity == "sensitive" and consent_id is None:
        raise MemoryRuleError("mục sensitive cần người dùng đồng ý trước")
    now = datetime.fromisoformat(repo.now())
    expires = (now + timedelta(days=TTL_DAYS)).isoformat(timespec="seconds")
    same = repo.query("SELECT memory_id FROM memory_items WHERE user_id = ? AND kind = ? AND value = ? AND deleted_at IS NULL",
                      (user_id, kind, value))  # fmt: skip
    if same:
        repo.query("UPDATE memory_items SET expires_at = ? WHERE memory_id = ?", (expires, same[0]["memory_id"]))
        return same[0]["memory_id"]
    memory_id = repo.new_id("mem")
    repo.query(
        """INSERT INTO memory_items (memory_id, user_id, kind, value, sensitivity, consent_id, source_message_id,
               source_trip_id, confirmed_by_user, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (memory_id, user_id, kind, value, sensitivity, consent_id, source_message_id, source_trip_id,
         now.isoformat(timespec="seconds"), expires),
    )  # fmt: skip
    return memory_id


def memory_read(user_id, kinds=None):
    """Mục còn hiệu lực của đúng user này (mới nhất trước). kinds: lọc theo loại."""
    expire_memory()
    rows = repo.query(f"SELECT {COLUMNS} FROM memory_items WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at DESC",
                      (user_id,))  # fmt: skip
    return [r for r in rows if kinds is None or r["kind"] in kinds]


def memory_update(user_id, memory_id, value):
    rows = repo.query("SELECT kind FROM memory_items WHERE memory_id = ? AND user_id = ? AND deleted_at IS NULL",
                      (memory_id, user_id))  # fmt: skip
    if not rows:
        return False
    repo.query("UPDATE memory_items SET value = ? WHERE memory_id = ? AND user_id = ?",
               (_check_value(rows[0]["kind"], value), memory_id, user_id))  # fmt: skip
    return True


def memory_delete(user_id, memory_id):
    rows = repo.query("UPDATE memory_items SET deleted_at = ? WHERE memory_id = ? AND user_id = ? AND deleted_at IS NULL"
                      " RETURNING memory_id", (repo.now(), memory_id, user_id))  # fmt: skip
    return bool(rows)
