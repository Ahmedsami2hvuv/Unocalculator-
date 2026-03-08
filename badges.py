# -*- coding: utf-8 -*-
"""
نظام الشارات (Badges) — بوت أونو
يُستدعى عند نهاية مباراة 2 لاعب: فوز (غرفة عشوائية فقط، ضد لاعب مختلف) أو خسارة.
"""
from database import db_query
import time

# ألوان الشارات (أونو)
BADGE_COLORS = {"🔴", "🟡", "🟢", "🔵"}
BOT_USER_ID = -1

# المستويات: (عدد الفوز المطلوب, المهلة بالأيام)
# 1–9: لون + رقم
# 10–12: أكشن (منع، تدوير، +2)
# 13–15: جوكر +1، +2، +4
BADGE_LEVELS = [
    (2, 5),   # 1  → 🔴1
    (5, 5),   # 2  → 🔴2
    (7, 5),   # 3  → 🔴3
    (10, 7),  # 4  → 🔴4
    (12, 7),  # 5  → 🔴5
    (15, 7),  # 6  → 🔴6
    (18, 10), # 7  → 🔴7
    (22, 10), # 8  → 🔴8
    (25, 10), # 9  → 🔴9
    (7, 7),   # 10 → منع
    (7, 7),   # 11 → تدوير
    (7, 7),   # 12 → +2
    (10, 10), # 13 → جوكر +1
    (10, 10), # 14 → جوكر +2
    (10, 10), # 15 → جوكر +4
]
MAX_LEVEL = len(BADGE_LEVELS)

# أسماء الشارات حسب المستوى (بدون لون — اللون من اختيار اللاعب)
BADGE_LABELS = {
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
    10: "منع", 11: "تدوير", 12: "+2",
    13: "جوكر +1", 14: "جوكر +2", 15: "جوكر +4",
}


def _ensure_badge_columns():
    """إضافة أعمدة الشارة لجدول users إن لم تكن موجودة."""
    alters = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_color VARCHAR(10) DEFAULT NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_level INT DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_streak INT DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_streak_started_at TIMESTAMP DEFAULT NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS badge_last_opponent_id BIGINT DEFAULT NULL;",
    ]
    for q in alters:
        try:
            db_query(q, commit=True)
        except Exception:
            pass


def get_badge_info(user_id: int) -> dict:
    """يرجع: badge_color, badge_level, badge_streak, streak_started_at, last_opponent_id، و label الشارة الحالية."""
    _ensure_badge_columns()
    row = db_query(
        "SELECT badge_color, badge_level, badge_streak, badge_streak_started_at, badge_last_opponent_id FROM users WHERE user_id = %s",
        (user_id,),
    )
    if not row:
        return {
            "badge_color": None,
            "badge_level": 0,
            "badge_streak": 0,
            "streak_started_at": None,
            "last_opponent_id": None,
            "current_badge_label": None,
        }
    r = row[0]
    level = int(r.get("badge_level") or 0)
    color = (r.get("badge_color") or "").strip() or None
    label = BADGE_LABELS.get(level) if level else None
    if label and color and level <= 9:
        current_badge_label = f"{color}{label}"
    elif label and color and level <= 12:
        current_badge_label = f"{color} {label}"
    elif label:
        current_badge_label = label  # جوكر
    else:
        current_badge_label = None
    return {
        "badge_color": color,
        "badge_level": level,
        "badge_streak": int(r.get("badge_streak") or 0),
        "streak_started_at": r.get("badge_streak_started_at"),
        "last_opponent_id": r.get("badge_last_opponent_id"),
        "current_badge_label": current_badge_label,
    }


def set_badge_color(user_id: int, color: str) -> bool:
    """تعيين لون الشارة (🔴/🟡/🟢/🔵). يُستدعى من واجهة اختيار اللون."""
    if color not in BADGE_COLORS:
        return False
    _ensure_badge_columns()
    try:
        db_query(
            "UPDATE users SET badge_color = %s WHERE user_id = %s",
            (color, user_id),
            commit=True,
        )
        return True
    except Exception:
        return False


def _streak_deadline_seconds(level: int) -> int:
    """المهلة بالأيام للمستوى الحالي (level=0 → أول شارة، ...) وتحويلها لثواني."""
    if level < 0 or level >= MAX_LEVEL:
        return 5 * 86400
    _, days = BADGE_LEVELS[level]
    return days * 86400


def _required_wins(level: int) -> int:
    """عدد الفوز المطلوب للوصول للمستوى التالي (level=0 → أول شارة، level=1 → ثاني شارة، ...)."""
    if level < 0 or level >= MAX_LEVEL:
        return 2
    return BADGE_LEVELS[level][0]


def badge_on_win(user_id: int, opponent_id: int, is_ranked: bool) -> dict:
    """
    يُستدعى عند فوز اللاعب في مباراة 2p.
    is_ranked: True فقط للغرف العشوائية (is_random=True)، False للغرف الترفيهية أو ضد البوت.
    opponent_id: الخصم (لا يكون BOT_USER_ID في المباريات المحسوبة).
    يُرجع: {
      "counted": bool,  # هل تم احتساب الفوز
      "reason": str,   # سبب عدم الحساب إن وُجد
      "new_badge": bool,
      "new_level": int,
      "new_badge_label": str,
      "message": str,
      "next_level_wins": int,
      "next_level_days": int,
    }
    """
    out = {
        "counted": False,
        "reason": "",
        "new_badge": False,
        "new_level": 0,
        "new_badge_label": None,
        "message": "",
        "next_level_wins": 0,
        "next_level_days": 0,
    }
    if not is_ranked or opponent_id is None or opponent_id == BOT_USER_ID:
        out["reason"] = "لا تُحسب هذه المباراة للشارات (غرفة ترفيه أو لعب ضد البوت)."
        return out
    _ensure_badge_columns()
    info = get_badge_info(user_id)
    color = info["badge_color"]
    level = info["badge_level"]
    streak = info["badge_streak"]
    last_opp = info["last_opponent_id"]
    streak_started = info["streak_started_at"]

    if not color:
        out["reason"] = "اختر لون شارتك أولاً من الإعدادات ← لون الشارة."
        return out

    if last_opp is not None and int(last_opp) == int(opponent_id):
        out["reason"] = "مبروك الفوز! لكن لن تُحسب للشارة؛ يجب أن تفوز ضد لاعبين مختلفين."
        return out

    now_ts = time.time()
    if streak_started:
        try:
            from datetime import datetime
            if isinstance(streak_started, (int, float)):
                start_ts = float(streak_started)
            else:
                start_ts = streak_started.timestamp() if hasattr(streak_started, "timestamp") else now_ts
        except Exception:
            start_ts = now_ts
        deadline = _streak_deadline_seconds(level if level >= 1 else 1)
        if now_ts - start_ts > deadline:
            streak = 0
            db_query(
                "UPDATE users SET badge_streak = 0, badge_streak_started_at = CURRENT_TIMESTAMP, badge_last_opponent_id = NULL WHERE user_id = %s",
                (user_id,),
                commit=True,
            )

    streak += 1
    required = _required_wins(level)
    days = BADGE_LEVELS[level][1] if 0 <= level < MAX_LEVEL else 5

    db_query(
        """UPDATE users SET
           badge_streak = %s,
           badge_streak_started_at = COALESCE(badge_streak_started_at, CURRENT_TIMESTAMP),
           badge_last_opponent_id = %s
           WHERE user_id = %s""",
        (streak, opponent_id, user_id),
        commit=True,
    )

    out["counted"] = True

    if streak >= required:
        new_level = min(level + 1, MAX_LEVEL)
        db_query(
            """UPDATE users SET badge_level = %s, badge_streak = 0, badge_streak_started_at = NULL, badge_last_opponent_id = NULL WHERE user_id = %s""",
            (new_level, user_id),
            commit=True,
        )
        new_label = BADGE_LABELS.get(new_level)
        if new_level <= 9:
            new_badge_label = f"{color}{new_label}"
        elif new_level <= 12:
            new_badge_label = f"{color} {new_label}"
        else:
            new_badge_label = new_label
        out["new_badge"] = True
        out["new_level"] = new_level
        out["new_badge_label"] = new_badge_label
        if new_level < MAX_LEVEL:
            next_wins, next_days = BADGE_LEVELS[new_level]
            out["next_level_wins"] = next_wins
            out["next_level_days"] = next_days
            out["message"] = f"🎉 تهانينا! حصلت على شارة {new_badge_label}.\n\nاستعد للمستوى التالي: عليك الفوز بـ {next_wins} مباريات متتالية ضد لاعبين مختلفين خلال {next_days} أيام للوصول للشارة التالية."
        else:
            out["message"] = f"🎉 تهانينا! حصلت على أعلى شارة: {new_badge_label}."
    else:
        out["message"] = f"✅ فوز محسوب للشارة! ({streak}/{required})"
        out["next_level_wins"] = required
        out["next_level_days"] = days

    return out


def badge_on_loss(user_id: int) -> None:
    """يُستدعى عند خسارة اللاعب: تصفير العداد فقط (الشارة الحالية تبقى، يعيد المحاولة من صفر للشارة التالية)."""
    _ensure_badge_columns()
    db_query(
        """UPDATE users SET badge_streak = 0, badge_streak_started_at = NULL, badge_last_opponent_id = NULL WHERE user_id = %s""",
        (user_id,),
        commit=True,
    )


def get_display_badge(user_id: int) -> str:
    """يرجع نص الشارة للعرض في البروفايل (مثلاً 🔴3 أو جوكر +4)."""
    info = get_badge_info(user_id)
    if info["current_badge_label"]:
        return info["current_badge_label"]
    return ""
