# -*- coding: utf-8 -*-
"""
وضع التدريب — ملف مستقل حتى لا يؤثر على لعب العادي.
• بدون توقيت (لا turn_timeout ولا auto_draw).
• البوت يرسل خطة لعب استراتيجية + الأوراق المتاحة.
"""
# لا نستورد من room_2p لتجنب الاستيراد الدائري؛ room_2p يمرّر لنا hand, top_card, current_color, valid_list


def _reason_for_card(card, top_card, current_color):
    """سبب إمكانية لعب الورقة (للعرض فقط)."""
    if any(x in card for x in ["🌈", "🔥", "💧", "🌊"]):
        return "wild"
    parts = card.split()
    top_parts = top_card.split()
    if len(parts) >= 2 and parts[0] in ("🔴", "🟡", "🟢", "🔵"):
        if parts[0] == current_color or (current_color == "ANY"):
            return "color"
        if len(top_parts) >= 2 and parts[1] == top_parts[1]:
            return "value"
    return "value"


def _get_plan_advice(user_id, hand, valid, top_card, current_color):
    """
    يبني جملة خطة لعب استراتيجية حسب الأوراق المتاحة.
    أولوية: منع → تحويل → +2 → نفس اللون → جوكر → افتراضي.
    """
    try:
        from i18n import t
    except Exception:
        return ""
    if not valid:
        return t(user_id, "training_plan_no_valid")
    has_skip = any("🚫" in c for c in valid)
    has_reverse = any("🔄" in c for c in valid)
    has_plus2 = any("+2" in c and c.split()[0] in ("🔴", "🟡", "🟢", "🔵") for c in valid)
    has_joker_draw = any(x in " ".join(valid) for x in ["💧", "🌊"])  # جوكر +1 أو +2: أي وقت، خصم يسحب، الدور يرجع لك
    has_wild4 = any("🔥" in c for c in valid)
    other_valid_no_wild4 = [c for c in valid if "🔥" not in c]
    has_same_color = any(
        _reason_for_card(c, top_card, current_color) == "color" for c in valid
    )
    has_wild = any(x in " ".join(valid) for x in ["🌈", "🔥"])
    if has_skip:
        return t(user_id, "training_plan_skip")
    if has_reverse:
        return t(user_id, "training_plan_reverse")
    if has_plus2:
        return t(user_id, "training_plan_plus2")
    if has_joker_draw:
        return t(user_id, "training_plan_joker_draw")
    if has_wild4:
        if other_valid_no_wild4:
            return t(user_id, "training_plan_wild4_has_other")
        return t(user_id, "training_plan_wild4_ok")
    if has_same_color:
        return t(user_id, "training_plan_same_color")
    if has_wild:
        return t(user_id, "training_plan_wild")
    return t(user_id, "training_plan_default")


# آخر رسالة تدريب لكل لاعب — نحذفها قبل إرسال جديدة أو نحدّثها حتى لا تتكدس
_training_msg_ids = {}


async def send_training_plan(room_id, bot, human_id, hand, top_card, current_color, valid_list):
    """
    إرسال خطة لعب + الأورقة النازلة + أوراق اللاعب + الأوراق المتاحة.
    نحذف رسالة التدريب السابقة (إن وُجدت) ثم نرسل رسالة جديدة، أو نحدّث نفس الرسالة إن أمكن.
    """
    try:
        from i18n import t
    except Exception as e:
        print(f"Training i18n: {e}")
        return
    hand_str = "، ".join(hand) if hand else "—"
    plan = _get_plan_advice(human_id, hand, valid_list, top_card, current_color)
    if valid_list:
        lines = []
        for c in valid_list:
            r = _reason_for_card(c, top_card, current_color)
            if r == "wild":
                lines.append(t(human_id, "training_hint_valid_reason_wild", card=c))
            elif r == "color":
                lines.append(t(human_id, "training_hint_valid_reason_color", card=c))
            else:
                lines.append(t(human_id, "training_hint_valid_reason_value", card=c))
        valid_line = "\n".join(lines)
    else:
        valid_line = t(human_id, "training_hint_no_valid")
    txt = t(
        human_id,
        "training_plan_intro",
        plan=plan,
        top_card=top_card,
        hand=hand_str,
        valid_line=valid_line,
    )
    try:
        prev_id = _training_msg_ids.pop(human_id, None)
        if prev_id:
            try:
                await bot.delete_message(human_id, prev_id)
            except Exception:
                pass
        msg = await bot.send_message(human_id, txt, parse_mode="Markdown")
        _training_msg_ids[human_id] = msg.message_id
    except Exception as e:
        print(f"Training send error: {e}")


def is_training_room(room):
    """هل الغرفة في وضع التدريب (لا نطبّق توقيت اللعب هنا)."""
    return bool(room.get("is_training"))
