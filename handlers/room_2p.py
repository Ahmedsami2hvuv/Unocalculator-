########## استيرادات ##########
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db_query
from config import IMG_UNO_SAFE_ME, IMG_UNO_SAFE_OPP, IMG_CATCH_SUCCESS, IMG_CATCH_PENALTY
import json, random, asyncio, uuid
from collections import Counter

########## المتغيرات العامة ##########
router = Router()
turn_timers = {}
TURN_TIMEOUT = 20
countdown_msgs = {}
auto_draw_tasks = {}
player_ui_msgs = {}  # المفتاح: user_id, القيمة: {'info': msg_id, 'buttons': msg_id}
challenge_timers = {}
challenge_countdown_msgs = {}
color_timers = {}
color_countdown_msgs = {}
pending_color_data = {}
color_timed_out = set()
temp_messages = {}  # المفتاح: user_id, القيمة: list of message_ids

########## الكلاسات ##########
class GameStates(StatesGroup):
    choosing_color = State()

########## دوال عامة (مساعدة وDB) ##########
def safe_load(data):
    if data is None: return []
    if isinstance(data, list): return data
    try: return json.loads(data)
    except: return []

def get_ordered_players(room_id):
    players = db_query("SELECT * FROM room_players WHERE room_id = %s", (room_id,))
    players.sort(key=lambda x: (x.get('join_order') or 0, x['user_id']))
    return players

########## دوال إنشاء وتوزيع الأوراق ##########
def generate_h2o_deck():
    colors = ['🔴', '🟡', '🟢', '🔵']
    deck = []
    for color in colors:
        deck.append(f"{color} 0")
        for i in range(1, 10):
            deck.extend([f"{color} {i}", f"{color} {i}"])
        deck.extend([f"{color} 🚫", f"{color} 🚫"]) # منع
        deck.extend([f"{color} 🔄", f"{color} 🔄"]) # تحويل
        deck.extend([f"{color} +2", f"{color} +2"]) # سحب 2

    # أوراق الأكشن الخاصة (وليست جوكرات)
    deck.append("💧 +1")  # جوكر +1 السابق - الآن ورقة أكشن عادية
    deck.append("🌊 +2")  # جوكر +2 السابق - الآن ورقة أكشن عادية

    # الجوكرات الحقيقية (التي تفتح قائمة ألوان أو تحدٍ)
    deck.extend(["🔥 جوكر+4"] * 4)      # جوكر +4 مع تحدي
    deck.extend(["🌈 جوكر ألوان"] * 4)   # جوكر ألوان فقط

    random.shuffle(deck)
    return deck

def sort_hand(hand):
    card_counts = Counter(card.split()[0] for card in hand if card.split()[0] in ['🔴', '🔵', '🟡', '🟢'])
    def card_sort_key(card):
        parts = card.split()
        color = parts[0]
        if any(x in card for x in ["🌈", "🔥", "💧", "🌊"]): return (3, 0, card)
        if color in ['🔴', '🔵', '🟡', '🟢']:
            count = card_counts.get(color, 0)
            return (0, -count, color, card) if count > 1 else (1, color, card)
        return (2, card)
    hand.sort(key=card_sort_key)
    return hand

def calculate_points(hand):
    total = 0
    for card in hand:
        if any(x in card for x in ["🌈", "🔥", "💧", "🌊"]): 
            total += 50
        elif any(x in card for x in ["🚫", "🔄", "⬆️2"]): 
            total += 20
        else:
            try: 
                total += int(card.split()[-1])
            except: 
                total += 10
    return total

########## دوال التحقق من صحة الورقة واللعب ##########


def check_validity(card, top_card, current_color):
    # color ANY = يمكنك لعب أي ورقة
    if current_color == "ANY":
        return True  
    if "🌈" in card:  # جوكر ألوان دائمًا مسموح
        return True
    if any(x in card for x in ["🔥", "💧", "🌊"]):
        return True
    parts = card.split()
    if len(parts) < 2: return False
    c_color, c_value = parts[0], parts[1]
    if c_color == current_color: 
        return True
    top_parts = top_card.split()
    top_value = top_parts[1] if len(top_parts) > 1 else top_parts[0]
    if c_value == top_value: 
        return True
    return False

########## دالة فحص عدد وتكرار كل ورقة بيد لاعب أو بالدكة ########## 

def cards_counter(deck):
    counts = Counter(deck)
    for card, count in counts.items():
        print(f"{card}: {count}")
    print(f"المجموع الكلي: {sum(counts.values())}")
    return counts

########## دوال إدارة التايمر والتأخير ##########
def cancel_color_timer(room_id):
    task = color_timers.pop(room_id, None)
    if task and not task.done(): task.cancel()
    cd = color_countdown_msgs.pop(room_id, None)
    if cd: asyncio.create_task(_delete_countdown(cd['bot'], cd['chat_id'], cd['msg_id']))
    pending_color_data.pop(room_id, None)

def cancel_auto_draw_task(room_id):
    if room_id in auto_draw_tasks:
        auto_draw_tasks[room_id].cancel()
        try:
            del auto_draw_tasks[room_id]
        except:
            pass

def cancel_challenge_timer(room_id):
    task = challenge_timers.pop(room_id, None)
    if task and not task.done(): task.cancel()
    cd = challenge_countdown_msgs.pop(room_id, None)
    if cd: asyncio.create_task(_delete_countdown(cd['bot'], cd['chat_id'], cd['msg_id']))


async def challenge_timeout_2p(room_id, bot):
    """
    إذا لم يرد الخصم خلال 20 ثانية، يُعتبر قبل السحب افتراضيًا.
    """
    try:
        await asyncio.sleep(20)
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data or room_data[0]['status'] != 'playing': return
        pending = pending_color_data.get(room_id)
        if not pending or pending.get('type') != 'challenge': return
        players = get_ordered_players(room_id)
        p_idx = pending['p_idx']
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']

        # سحب 4 كروت للخصم
        deck = safe_load(room_data[0]['deck'])
        opp_hand = safe_load(players[opp_idx]['hand'])
        for _ in range(4):
            if deck: opp_hand.append(deck.pop(0))
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)

        # إخطار الجميع
        await bot.send_message(opp_id, "⏰ انتهى الوقت! تم قبول السحب تلقائياً (سحبت 4 ورقات).")
        await bot.send_message(players[p_idx]['user_id'], "تم قبول السحب افتراضيًا. يمكنك اللعب الآن بأي لون.")

        # تحديث move (الدور يرجع للاعب الأصلي، current_color='ANY' لتكون أي لون مسموحة)
        db_query("UPDATE rooms SET turn_index = %s, current_color = 'ANY' WHERE room_id = %s", (p_idx, room_id), commit=True)

        # حذف بيانات التحدي المؤقتة
        pending_color_data.pop(room_id, None)
        challenge_timers.pop(room_id, None)
        challenge_countdown_msgs.pop(room_id, None)

        # تحديث الواجهات للجميع
        await refresh_ui_2p(room_id, bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[challenge_timeout_2p] Error: {e}")

def cancel_timer(room_id):
    # إلغاء عداد الدور
    task = turn_timers.pop(room_id, None)
    if task and not task.done():
        task.cancel()
    
    # التعديل هنا: لا تمسح الرسالة إذا كانت هي واجهة اللعب الأساسية
    cd = countdown_msgs.pop(room_id, None)
    if cd and not cd.get('is_main_message'):
        asyncio.create_task(_delete_countdown(cd['bot'], cd['chat_id'], cd['msg_id']))
    
    # إلغاء تايمر اختيار اللون
    color_task = color_timers.pop(room_id, None)
    if color_task and not color_task.done():
        color_task.cancel()
    
    # إلغاء رسالة عداد اختيار اللون
    color_cd = color_countdown_msgs.pop(room_id, None)
    if color_cd:
        asyncio.create_task(_delete_countdown(color_cd['bot'], color_cd['chat_id'], color_cd['msg_id']))
    
    # إلغاء تايمر التحدي
    challenge_task = challenge_timers.pop(room_id, None)
    if challenge_task and not challenge_task.done():
        challenge_task.cancel()
    
    # إلغاء رسالة عداد التحدي
    challenge_cd = challenge_countdown_msgs.pop(room_id, None)
    if challenge_cd:
        asyncio.create_task(_delete_countdown(challenge_cd['bot'], challenge_cd['chat_id'], challenge_cd['msg_id']))

async def _delete_countdown(bot, chat_id, msg_id):
    try:
        await bot.delete_message(chat_id, msg_id)
    except:
        pass

async def turn_timeout_2p(room_id, bot, expected_turn):
    try:
        players = get_ordered_players(room_id)
        if expected_turn >= len(players): 
            return
            
        p_id = players[expected_turn]['user_id']
        
        # العداد الأصلي (20 ثانية)
        for step in range(10, 0, -1):
            try:
                await asyncio.sleep(2)
                # ... كود التحديث ...
            except Exception as e:
                print(f"فشل تحديث التايمر لكن سأستمر: {e}")
                continue # لا تتوقف، استمر بالعد
            
            # التحقق من الغرفة في كل دورة
            room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
            if not room_data:
                return
            room = room_data[0]
            
            if room['status'] != 'playing' or room['turn_index'] != expected_turn:
                return
            
            if room_id not in turn_timers:
                return
            
            remaining = step * 2
            
            # تحديث رسالة المعلومات باستخدام الدالة المخصصة
            await send_or_update_game_ui(room_id, bot, p_id, remaining)

        # بعد انتهاء الوقت، ننفذ العقوبة
        # --- التحقق من الغرفة والدور قبل تنفيذ العقوبة ---
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: 
            return
        room = room_data[0]
        
        if room['status'] != 'playing' or room['turn_index'] != expected_turn: 
            return
        
        players = get_ordered_players(room_id)
        curr_p = players[expected_turn]
        p_id = curr_p['user_id']
        opp_id = players[(expected_turn + 1) % 2]['user_id']
        p_name = curr_p.get('player_name') or "لاعب"
        curr_hand = safe_load(curr_p['hand'])

        # --- تنفيذ المنطق: عقوبة ضياع الوقت ---
        deck = safe_load(room['deck'])
        if not deck:
            deck = generate_h2o_deck()
            random.shuffle(deck)
        
        penalty_card = deck.pop(0)
        curr_hand.append(penalty_card)
        
        # نقل الدور للمقابل
        next_turn = (expected_turn + 1) % 2
        
        # تحديث قاعدة البيانات
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                (json.dumps(curr_hand), p_id), commit=True)
        db_query("UPDATE rooms SET turn_index = %s, deck = %s WHERE room_id = %s", 
                (next_turn, json.dumps(deck), room_id), commit=True)

        # تنظيف العدادات
        turn_timers.pop(room_id, None)

        # إبلاغ اللاعبين
        msgs = {
            p_id: f"⏰ خلص وقتك! تعاقبت بسحب ورقة ({penalty_card}) وانتقل الدور للمنافس.",
            opp_id: f"⏰ {p_name} خلص وقته وتعاقب بسحب ورقة من الكومة، الدور صار إلك ✅"
        }
        await refresh_ui_2p(room_id, bot, msgs)

    except asyncio.CancelledError:
        # تم إلغاء التايمر
        raise
        
    except Exception as e:
        print(f"Timer error 2p: {e}")

async def color_timeout_2p(room_id, bot, player_id):
    try:
        cd_info = color_countdown_msgs.get(room_id)
        if not cd_info:
            return
            
        for step in range(20, 0, -1):
            await asyncio.sleep(1)
            
            # التحقق من الغرفة
            room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
            if not room_data:
                return
            room = room_data[0]
            
            if room['status'] != 'playing' or room_id not in color_timers:
                return
            
            remaining = step
            
            # بناء الشريط (10 نقاط = 20 ثانية)
            steps_left = (remaining + 1) // 2  # 20 ثانية = 10 خطوات
            bar_parts = []
            for s in range(10):
                if s < steps_left:
                    if remaining > 10:
                        bar_parts.append("🟢")
                    elif remaining > 5:
                        bar_parts.append("🟡")
                    else:
                        bar_parts.append("🔴")
                else:
                    bar_parts.append("⚫")
            bar = "".join(bar_parts)
            
            # تحديث الرسالة
            try:
                await bot.edit_message_text(
                    chat_id=cd_info['chat_id'],
                    message_id=cd_info['msg_id'],
                    text=f"⏳ الوقت المتبقي: {remaining} ثانية لاختيار اللون\n{bar}"
                )
            except Exception:
                # إذا فشل التعديل (الرسالة محذوفة)، نرسل رسالة جديدة
                try:
                    new_msg = await bot.send_message(
                        cd_info['chat_id'],
                        f"⏳ الوقت المتبقي: {remaining} ثانية لاختيار اللون\n{bar}"
                    )
                    cd_info['msg_id'] = new_msg.message_id
                except:
                    pass
            
            await asyncio.sleep(1)
        
        # بعد انتهاء الوقت (لم يتم اختيار لون)، نحذف رسالة العداد
        if cd_info:
            try: await bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except: pass
            
        color_timers.pop(room_id, None)
        pdata = pending_color_data.pop(room_id, None)
        if not pdata: return
        
        color_timed_out.add(room_id)
        card = pdata['card_played']
        p_idx = pdata['p_idx']
        prev_color = pdata['prev_color']
        chosen_color = random.choice(['🔴', '🔵', '🟡', '🟢'])
        
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: return
        room = room_data[0]
        if room['status'] != 'playing': return
        
        players = get_ordered_players(room_id)
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']
        p_name = players[p_idx].get('player_name') or "لاعب"
        
        if "🔥" in card:
            db_query("UPDATE rooms SET top_card = %s, current_color = %s WHERE room_id = %s", (f"{card} {chosen_color}", chosen_color, room_id), commit=True)
            kb = [[InlineKeyboardButton(text="🕵️‍♂️ أتحداك", callback_data=f"rs_y_{room_id}_{prev_color}_{chosen_color}"), 
                   InlineKeyboardButton(text="✅ قبول", callback_data=f"rs_n_{room_id}_{chosen_color}")]]
            await bot.send_message(opp_id, f"🚨 {p_name} لعب 🔥 +4 وغير اللون لـ {chosen_color}!",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            cd_msg = await bot.send_message(opp_id, "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢")
            challenge_countdown_msgs[room_id] = {'bot': bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
            challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, bot))
            await bot.send_message(player_id, f"⏰ انتهى الوقت! تم اختيار اللون {chosen_color} تلقائياً. بانتظار رد الخصم...")
            return
            
        deck = safe_load(room['deck'])
        alerts = {}
        penalty = 1 if "💧" in card else (2 if "🌊" in card else 0)
        next_turn = p_idx  # القيمة الافتراضية (للجوكرات ذات العقوبة)
        
        if penalty > 0:
            if not deck:
                discard = safe_load(room['discard_pile'])
                if discard:
                    deck = discard
                    random.shuffle(deck)
                    db_query("UPDATE rooms SET discard_pile = '[]' WHERE room_id = %s", (room_id,), commit=True)
                else:
                    deck = generate_h2o_deck()
            opp_h = safe_load(players[opp_idx]['hand'])
            for _ in range(penalty):
                if deck: opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_h), opp_id), commit=True)
            alerts[opp_id] = f"⏰ {p_name} ما اختار اللون بالوقت! تم اختيار {chosen_color} تلقائياً وسحبك {penalty} ورقة والدور رجع له!"
            alerts[player_id] = f"⏰ انتهى الوقت! تم اختيار اللون {chosen_color} تلقائياً."
        else:
            next_turn = (p_idx + 1) % 2  # الجوكر الملون العادي: الدور يذهب للخصم
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} والدور رجع له!"
            alerts[player_id] = f"🎨 اخترت اللون {chosen_color} والدور رجع لك!"
            
        db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s", 
                (f"{card} {chosen_color}", chosen_color, next_turn, json.dumps(deck), room_id), commit=True)
        
        turn_timers.pop(room_id, None)
        countdown_msgs.pop(room_id, None)
        await refresh_ui_2p(room_id, bot, alerts)
        
    except asyncio.CancelledError:
        cd_info = color_countdown_msgs.get(room_id)
        if cd_info:
            try: await bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except: pass
        raise
    except Exception as e:
        print(f"Color timer error 2p: {e}")


async def background_auto_draw(room_id, bot, curr_idx):
    """دالة السحب التلقائي: تنتظر 5 ثوانٍ مع تحديث واجهة اللعب، تسحب ورقة، ثم تتصرف حسب صلاحيتها."""
    try:
        cancel_auto_draw_task(room_id)

        players = get_ordered_players(room_id)
        if curr_idx >= len(players): 
            return
        p_id = players[curr_idx]['user_id']
        p_name = players[curr_idx].get('player_name') or "لاعب"

        # العد التنازلي من خلال تحديث واجهة اللعب فقط
        for sec in range(5, 0, -1):
            # تحديث واجهة اللاعب مع رسالة العد التنازلي
            await send_or_update_game_ui(
                room_id, bot, p_id,
                remaining_seconds=None,
                alert_text=f"⏳ ما عندك ورقة مناسبة! راح اسحبلك تلقائياً بعد {sec} ثواني..."
            )
            await asyncio.sleep(1)

        # التحقق من أن اللاعب لا يزال في نفس الدور
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: 
            return
        room = room_data[0]
        if room['turn_index'] != curr_idx:
            return

        deck = safe_load(room['deck'])
        if not deck:
            deck = generate_h2o_deck()
            random.shuffle(deck)

        curr_hand = safe_load(players[curr_idx]['hand'])
        new_card = deck.pop(0)
        curr_hand.append(new_card)

        # تحديث قاعدة البيانات
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                 (json.dumps(curr_hand), p_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", 
                 (json.dumps(deck), room_id), commit=True)

        # التحقق من صلاحية الورقة الجديدة
        if check_validity(new_card, room['top_card'], room['current_color']):
            await refresh_ui_2p(room_id, bot, {p_id: f"✅ سحبت ({new_card}) وتشتغل! الك 20 ثانية."})
        else:
            # الورقة غير صالحة: نمرر الدور للخصم فوراً
            next_turn = (curr_idx + 1) % 2
            db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", 
                     (next_turn, room_id), commit=True)
            opp_id = players[next_turn]['user_id']
            alerts = {
                p_id: f"📥 سحبت ({new_card}) وما تشتغل ❌ تم تمرير دورك.",
                opp_id: f"➡️ {p_name} سحب ورقة ({new_card}) وما اشتغلت، هسة دورك!"
            }
            await refresh_ui_2p(room_id, bot, alerts)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in background_auto_draw: {e}")
    finally:
        if room_id in auto_draw_tasks:
            del auto_draw_tasks[room_id]
            
async def send_temp_message_and_delete(bot, user_id, text, delay=1.5):
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except:
        pass

async def start_turn_timer(room_id, bot, p_idx):
    try:
        for sec in range(20, 0, -1):
            await asyncio.sleep(1)
            room_data = db_query("SELECT turn_index FROM rooms WHERE room_id = %s", (room_id,))
            if not room_data or room_data[0]['turn_index'] != p_idx:
                return

        await force_draw_and_pass(room_id, bot, p_idx)
    except asyncio.CancelledError:
        pass

async def force_draw_and_pass(room_id, bot, p_idx):
    room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
    if not room_data: return
    room = room_data[0]
    players = get_ordered_players(room_id)
    user_id = players[p_idx]['user_id']

    deck = safe_load(room['deck'])
    if deck:
        new_card = deck.pop(0)
        hand = safe_load(players[p_idx]['hand'])
        hand.append(new_card)
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(hand), user_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)

    next_t = (p_idx + 1) % 2
    db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_t, room_id), commit=True)
    await refresh_ui_2p(room_id, bot, {user_id: "⏰ انتهى وقتك! سحبت ورقة وتم تمرير الدور."})
    turn_timers[room_id] = asyncio.create_task(start_turn_timer(room_id, bot, next_t))

########## دوال واجهة المستخدم (UI) والرسائل ##########


async def send_or_update_game_ui(room_id, bot, user_id, remaining_seconds=None, alert_text=None):
    """النسخة الكاملة: تجمع بين تفاصيلك القديمة وإصلاح مشكلة تحديث الرسالة"""
    try:
        # جلب بيانات الغرفة واللاعبين
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: return
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']
        
        current_player = next((p for p in players if p['user_id'] == user_id), None)
        if not current_player: return
        
        hand = sort_hand(safe_load(current_player['hand']))
        is_my_turn = (user_id == players[curr_idx]['user_id'])
        
        # 1. بناء نص معلومات اللاعبين
        players_info = []
        for pl_idx, pl in enumerate(players):
            pl_name = pl.get('player_name') or 'لاعب'
            pl_cards = len(safe_load(pl['hand']))
            star = "✅" if pl_idx == curr_idx else "⏳"
            players_info.append(f"{star} {pl_name}: {pl_cards} ورقة")
        
        info_text = f"📦 السحب: {len(safe_load(room['deck']))} ورقه\n"
        info_text += f"🗑 النازلة: {len(safe_load(room.get('discard_pile', '[]')))+1} ورقه\n"
        info_text += "\n".join(players_info)
        
        if alert_text:
            info_text += f"\n──────────────\n📢 {alert_text}"
        
        # 2. بناء شريط الوقت (🟢🟡🔴) - حافظنا على منطقك القديم
        if is_my_turn:
            remaining = remaining_seconds if remaining_seconds is not None else 20
            total_steps = 10
            steps_left = (remaining + 1) // 2
            bar_parts = []
            for s in range(total_steps):
                if s < steps_left:
                    if remaining > 10: bar_parts.append("🟢")
                    elif remaining > 5: bar_parts.append("🟡")
                    else: bar_parts.append("🔴")
                else:
                    bar_parts.append("⚫")
            bar = "".join(bar_parts)
            info_text += f"\n──────────────\n⏳ باقي {remaining} ثانية\n{bar}\n✅ دورك 👍🏻"
        else:
            info_text += f"\n──────────────\n⏳ مو دورك"
            
        info_text += f"\n🃏 الورقة النازلة: [ {room['top_card']} ]"
        info_text += f"\n\n════════════════════\n🃏 **أوراقك:**"

        # 3. بناء الأزرار
        kb = []
        row = []
        for card_idx, card in enumerate(hand):
            row.append(InlineKeyboardButton(text=card, callback_data=f"pl_{room_id}_{card_idx}"))
            if len(row) == 3:
                kb.append(row); row = []
        if row: kb.append(row)
        
        controls = []
        if is_my_turn:
            if room_id in auto_draw_tasks:
                controls.append(InlineKeyboardButton(text="➡️ مرر الدور", callback_data=f"pass_{room_id}"))
            if len(hand) == 2:
                controls.append(InlineKeyboardButton(text="🚨 اونو!", callback_data=f"un_{room_id}"))
        
        # منطق الصيدة
        opp = players[1] if players[0]['user_id'] == user_id else players[0]
        opp_h = safe_load(opp.get('hand', '[]'))
        if len(opp_h) == 1 and not str(opp.get('said_uno', 'false')).lower() in ['true', '1']:
            controls.append(InlineKeyboardButton(text="🪤 صيدة!", callback_data=f"ct_{room_id}"))
        
        if controls: kb.append(controls)
        kb.append([InlineKeyboardButton(text="🚪 انسحاب", callback_data=f"ex_{room_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=kb)

        # 4. التحديث الذكي (الجزء الأهم لثبات الرسالة)
        old_msg_id = player_ui_msgs.get(user_id, {}).get('game_ui')
        
        if old_msg_id:
            try:
                # نحاول نعدل الرسالة فقط
                await bot.edit_message_text(
                    text=info_text, 
                    chat_id=user_id, 
                    message_id=old_msg_id, 
                    reply_markup=markup
                )
                return # التحديث نجح، نطلع من الدالة
            except Exception as e:
                # إذا الخطأ هو أن النص لم يتغير، نتجاهله ولا نفعل شيئاً
                if "message is not modified" in str(e).lower():
                    return
                # أي خطأ آخر (مثل الرسالة انحذفت من قبل المستخدم)، نكمل عشان نرسل وحدة جديدة
                pass

        # إرسال رسالة جديدة فقط عند الضرورة القصوى
        new_msg = await bot.send_message(user_id, info_text, reply_markup=markup)
        player_ui_msgs.setdefault(user_id, {})['game_ui'] = new_msg.message_id

    except Exception as e:
        print(f"UI Error: {e}")


async def refresh_ui_2p(room_id, bot, alert_msg_dict=None):
    """تحديث واجهة المستخدم بالكامل (رسالة واحدة موحدة تحتوي على المعلومات والأزرار)."""
    try:
        cancel_timer(room_id)

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: return
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']

        for i, p in enumerate(players):
            user_id = p['user_id']
            is_my_turn = (i == curr_idx)
            alert_text = alert_msg_dict.get(user_id) if alert_msg_dict else None

            if is_my_turn and room_id in countdown_msgs:
                remaining = 20
                await send_or_update_game_ui(room_id, bot, user_id, remaining_seconds=remaining, alert_text=alert_text)
            else:
                await send_or_update_game_ui(room_id, bot, user_id, alert_text=alert_text)

        curr_p = players[curr_idx]
        curr_hand = safe_load(curr_p['hand'])
        is_playable = any(check_validity(c, room['top_card'], room['current_color']) for c in curr_hand)

        if not is_playable:
            if room_id not in auto_draw_tasks or auto_draw_tasks[room_id].done():
                auto_draw_tasks[room_id] = asyncio.create_task(background_auto_draw(room_id, bot, curr_idx))
        else:
            if room_id not in turn_timers:
                turn_timers[room_id] = asyncio.create_task(turn_timeout_2p(room_id, bot, curr_idx))

    except Exception as e:
        print(f"Error in refresh_ui_2p: {e}")

async def delete_temp_messages(user_id, bot, exclude_ids=None):
    """حذف جميع الرسائل الجانبية لمستخدم معين، مع استثناء معرفات معينة"""
    if user_id in temp_messages:
        for msg_id in temp_messages[user_id]:
            # لا تحذف إذا كان المعرف في قائمة الاستثناء
            if exclude_ids and msg_id in exclude_ids:
                continue
            try:
                await bot.delete_message(user_id, msg_id)
            except:
                pass
        # تنظيف القائمة بعد الحذف
        temp_messages[user_id] = [msg_id for msg_id in temp_messages[user_id] 
                                  if exclude_ids and msg_id in exclude_ids]

async def send_temp_message_and_delete(bot, user_id, text, delay=1.5):
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except:
        pass

#####3) دالة حذف رسال�� عداد (للاستخدام الداخلي)######
async def _delete_countdown(bot, chat_id, msg_id):
    try: 
        await bot.delete_message(chat_id, msg_id)
    except: 
        pass

#### دوال إرسال صور مؤقتة #####

async def _send_temp_photo(bot, chat_id, photo_id, delay=3):
    try:
        msg = await bot.send_photo(chat_id, photo_id)
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, msg.message_id)
        except:
            pass
    except:
        pass

async def _send_photo_then_schedule_delete(bot, chat_id, photo_id, delay=3):
    try:
        msg = await bot.send_photo(chat_id, photo_id)
        async def _del():
            await asyncio.sleep(delay)
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except:
                pass
        asyncio.create_task(_del())
    except:
        pass

    
########## دوال الأكشن والأوراق الخاصة ##########

async def handle_draw1_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts):
    """معالجة جوكر +1 (💧) - كأكشن: يسحب الخصم ورقة واحدة"""
    next_turn = p_idx  # الدور يبقى عند اللاعب
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = safe_load(room['deck'])
    opp_hand = safe_load(players[opp_idx]['hand'])
    
    # سحب ورقة واحدة للخصم
    drawn_cards = []
    for _ in range(1):
        if deck:
            drawn_cards.append(deck.pop(0))
    
    if drawn_cards:
        opp_hand.extend(drawn_cards)
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                (json.dumps(opp_hand), opp_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", 
                (json.dumps(deck), room_id), commit=True)
    
    alerts[opp_id] = f"💧 {p_name} لعب جوكر +1 وسحبك ورقة! 🎯"
    alerts[c.from_user.id] = f"💧 لعبت جوكر +1 وسحبت الخصم ورقة! ✅"
    db_query("UPDATE rooms SET top_card = %s, current_color = 'ANY' WHERE room_id = %s", (card, room_id), commit=True)
    return next_turn

async def handle_draw2_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts):
    """معالجة جوكر +2 (🌊) - كأكشن: يسحب الخصم ورقتين"""
    next_turn = p_idx
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = safe_load(room['deck'])
    opp_hand = safe_load(players[opp_idx]['hand'])
    drawn_cards = []
    for _ in range(2):
        if deck:
            drawn_cards.append(deck.pop(0))
    if drawn_cards:
        opp_hand.extend(drawn_cards)
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                (json.dumps(opp_hand), opp_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", 
                (json.dumps(deck), room_id), commit=True)

    alerts[opp_id] = f"🌊 {p_name} لعب جوكر +2 وسحبك ورقتين! 🎯"
    alerts[c.from_user.id] = f"🌊 لعبت جوكر +2 وسحبت الخصم ورقتين! ✅"
    db_query("UPDATE rooms SET top_card = %s, current_color = 'ANY' WHERE room_id = %s", (card, room_id), commit=True)
    return next_turn


async def handle_colored_draw2_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts):
    """معالجة ورقة +2 الملونة - تسحب الخصم ورقتين والدور يبقى للاعب مع تثبيت لون الورقة"""
    next_turn = p_idx  # الدور يبقى عند نفس اللاعب
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = safe_load(room['deck'])
    opp_hand = safe_load(players[opp_idx]['hand'])
    drawn_cards = []
    for _ in range(2):
        if not deck:
            deck = generate_h2o_deck()
            random.shuffle(deck)
        drawn_cards.append(deck.pop(0))
    opp_hand.extend(drawn_cards)
    card_color = card.split()[0]
    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
            (json.dumps(opp_hand), opp_id), commit=True)
    db_query("""
        UPDATE rooms 
        SET top_card = %s, current_color = %s, turn_index = %s, deck = %s 
        WHERE room_id = %s
    """, (card, card_color, next_turn, json.dumps(deck), room_id), commit=True)
    alerts[opp_id] = f"{card_color} {p_name} لعب +2 ملونة وسحبك ورقتين! 🎯"
    alerts[c.from_user.id] = f"✅ لعبت +2 ملونة، سحبت الخصم وباقي دورك!"
    return next_turn

async def handle_skip_card(c, room_id, p_idx, opp_id, p_name, card, next_turn, alerts):
    """معالجة ورقة منع (🚫) - تمنع اللاعب التالي"""
    next_turn = p_idx  # الدور يرجع للاعب نفسه
    alerts[opp_id] = f"🚫 {p_name} لعب ورقة منع!"
    alerts[c.from_user.id] = f"🚫 لعبت ورقة منع!"
    return next_turn

async def handle_reverse_card(c, room_id, p_idx, opp_id, p_name, card, next_turn, alerts):
    """معالجة ورقة عكس (🔄) - في 2 لاعبين ترجع الدور للاعب نفسه"""
    next_turn = p_idx  # الدور يرجع للاعب نفسه
    alerts[opp_id] = f"🔄 {p_name} لعب ورقة عكس!"
    alerts[c.from_user.id] = f"🔄 لعبت ورقة عكس!"
    return next_turn

async def handle_wild_draw4_card(c, state: FSMContext, room_id, p_idx, opp_id, p_name, card, discard_pile, hand, room):
    """
    عند لعب جوكر +4: ترسل رسالة للخصم (هل تتحدى أم تقبل؟) وتمنع اللاعب الحالي من اللعب حتى يرد الخصم.
    """
    try:
        pending_color_data[room_id] = {
            'card_played': card,
            'p_idx': p_idx,
            'opp_id': opp_id,
            'p_name': p_name,
            'type': 'challenge',
            'prev_top_card': room['top_card'],
            'prev_color': room['current_color'],
        }
        db_query("UPDATE rooms SET top_card = %s, discard_pile = %s, current_color = 'ANY' WHERE room_id = %s",
                 (card, json.dumps(discard_pile), room_id), commit=True)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🕵️‍♂️ أتحداك", callback_data=f"challenge_y_{room_id}"),
                InlineKeyboardButton(text="✅ أقبل السحب", callback_data=f"challenge_n_{room_id}")
            ]
        ])
        msg = await c.bot.send_message(
            opp_id,
            f"🔥 {p_name} لعب جوكر +4!\nهل تريد التحدي؟ لديك 20 ثانية للاختيار.",
            reply_markup=kb
        )
        cd_msg = await c.bot.send_message(opp_id, "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢")
        challenge_countdown_msgs[room_id] = {'bot': c.bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
        challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, c.bot))
        await c.answer("✅ بانتظار رد الخصم على جوكر +4، لا يمكنك اللعب الآن.", show_alert=True)
        await send_or_update_game_ui(room_id, c.bot, c.from_user.id, alert_text="🔥 لعبت جوكر +4!\nبانتظار رد الخصم.", remaining_seconds=None)
    except Exception as e:
        print(f"[handle_wild_draw4_card] Error: {e}")
        await c.answer("❌ حدث خطأ أثناء معالجة جوكر +4", show_alert=True)

async def handle_wild_color_card(c, state: FSMContext, room_id, p_idx, opp_id, p_name, hand, card, discard_pile, room):
    """معالجة جوكر الألوان (🌈)"""
    await state.set_state(GameStates.choosing_color)
    await state.update_data(
        room_id=room_id, 
        card_played=card, 
        p_idx=p_idx, 
        prev_color=room['current_color']
    )
    color_kb = [
        [
            InlineKeyboardButton(text="🔴 أحمر", callback_data="cl_🔴"),
            InlineKeyboardButton(text="🔵 أزرق", callback_data="cl_🔵")
        ],
        [
            InlineKeyboardButton(text="🟡 أصفر", callback_data="cl_🟡"),
            InlineKeyboardButton(text="🟢 أخضر", callback_data="cl_🟢")
        ]
    ]
    await c.message.edit_text(
        "🎨 اختر اللون الجديد:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=color_kb)
    )
    db_query("UPDATE rooms SET discard_pile = %s WHERE room_id = %s", 
            (json.dumps(discard_pile), room_id), commit=True)
    pending_color_data[room_id] = {
        'card_played': card, 
        'p_idx': p_idx, 
        'prev_color': room['current_color']
    }
    cd_msg = await c.bot.send_message(
        c.from_user.id, 
        "⏳ باقي 20 ثانية لاختيار اللون\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢"
    )
    if c.from_user.id not in temp_messages:
        temp_messages[c.from_user.id] = []
    temp_messages[c.from_user.id].append(cd_msg.message_id)
    color_timers[room_id] = asyncio.create_task(
        color_timeout_2p(room_id, c.bot, c.from_user.id))

async def start_new_round(room_id, bot, start_turn_idx=0, alert_msgs=None):
    try:
        room_res = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_res: return
        players = get_ordered_players(room_id)
        
        # 🔴🔴🔴 أضف هذه الأسطر هنا 🔴🔴🔴
        # مسح معرفات الرسائل القديمة للاعبين
        for p in players:
            if p['user_id'] in player_ui_msgs:
                player_ui_msgs[p['user_id']] = {}
        # 🔴🔴🔴 نهاية الإضافة 🔴🔴🔴

        deck = generate_h2o_deck()
        
        # توزيع الأوراق على كل اللاعبين
        for p in players:
            hand = [deck.pop(0) for _ in range(7)]
            db_query("UPDATE room_players SET hand = %s, said_uno = FALSE, last_msg_id = NULL, is_ready = FALSE WHERE user_id = %s", (json.dumps(hand), p['user_id']), commit=True)
        
        # اختيار ورقة البداية (ما تكون جوكر)
        while any(x in deck[0] for x in ["🌈", "🔥", "💧", "🌊"]): 
            random.shuffle(deck)
        top_card = deck.pop(0)
        current_color = top_card.split()[0]
        
        # تحديث الغرفة في قاعدة البيانات
        db_query("UPDATE rooms SET deck = %s, top_card = %s, current_color = %s, turn_index = %s, discard_pile = '[]', status = 'playing' WHERE room_id = %s", 
                 (json.dumps(deck), top_card, current_color, start_turn_idx, room_id), commit=True)
        
        # إرسال رسالة بداية اللعبة للاعبين الاثنين
        for p in players:
            try:
                await bot.send_message(p['user_id'], "🎮 بدأت اللعبة! استعد...")
            except:
                pass
        
        # تحديث الواجهة للاعبين الاثنين
        await refresh_ui_2p(room_id, bot, alert_msgs)
        
    except Exception as e: 
        print(f"Error in start_new_round: {e}")


########## الهاندلرز (Handlers) #########


@router.callback_query(F.data.startswith("pl_"))
async def handle_play(c: types.CallbackQuery, state: FSMContext):
    try:
        parts = c.data.split("_")
        idx = int(parts[-1])
        room_id = "_".join(parts[1:-1])
        
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة", show_alert=True)
        room = room_data[0]
        players = get_ordered_players(room_id)
        p_idx = room['turn_index']
        if players[p_idx]['user_id'] != c.from_user.id:
            return await c.answer("❌ مو دورك! انتظر الخصم يلعب.", show_alert=True)

        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
        await asyncio.sleep(0)
        
        hand = sort_hand(safe_load(players[p_idx]['hand']))
        if idx >= len(hand):
            return await c.answer("⚠️ حدث خطأ في اختيار الورقة", show_alert=True)
        
        card = hand[idx]
        p_name = players[p_idx].get('player_name') or "لاعب"
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']
        
        if not check_validity(card, room['top_card'], room['current_color']):
            deck = safe_load(room['deck'])
            penalty_cards = []
            if deck:
                penalty_cards.append(deck.pop(0))
                hand.extend(penalty_cards)
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                        (json.dumps(hand), c.from_user.id), commit=True)
                db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", 
                        (json.dumps(deck), room_id), commit=True)
            alerts = {
                c.from_user.id: f"⛔ ورقة خطأ! سحبت ورقة عقوبة.",
                opp_id: f"⚠️ {p_name} حاول يلعب ورقة خطأ وتعاقب."
            }
            return await refresh_ui_2p(room_id, c.bot, alerts)
        
        hand.pop(idx)
        was_uno_said = str(players[p_idx].get('said_uno', False)).lower() in ['true', '1', 'true']
        updated_said_uno = was_uno_said if len(hand) == 1 else False
        
        db_query("UPDATE room_players SET hand = %s, said_uno = %s WHERE user_id = %s", 
                (json.dumps(hand), updated_said_uno, c.from_user.id), commit=True)
        discard_pile = safe_load(room.get('discard_pile', '[]'))
        discard_pile.append(room['top_card'])
        
        alerts = {}
        
        if len(hand) == 0:
            opp_hand = safe_load(players[opp_idx]['hand'])
            points = calculate_points(opp_hand)
            current_points = players[p_idx].get('online_points', 0)
            db_query("UPDATE users SET online_points = %s WHERE user_id = %s", 
                    (current_points + points, c.from_user.id), commit=True)
            db_query("UPDATE rooms SET discard_pile = %s, top_card = %s, current_color = %s WHERE room_id = %s", 
                    (json.dumps(discard_pile), card, card.split()[0], room_id), commit=True)
            db_query("DELETE FROM room_players WHERE room_id = %s", (room_id,), commit=True)
            win_text = f"🏆 **{p_name} فاز بالجولة!** 🏆\n📊 حصل على {points} نقطة."
            from handlers.common import create_replay_session, build_game_end_keyboard
            replay_id = create_replay_session(players, room, '2p', win_text)
            for p in players:
                end_kb = build_game_end_keyboard(replay_id, p['user_id'])
                await c.bot.send_message(p['user_id'], win_text, reply_markup=end_kb)
            db_query("DELETE FROM rooms WHERE room_id = %s", (room_id,), commit=True)
            return

        next_turn = (p_idx + 1) % 2
        new_color = card.split()[0]
        db_query("UPDATE rooms SET top_card = %s, current_color = %s, discard_pile = %s WHERE room_id = %s", 
                (card, new_color, json.dumps(discard_pile), room_id), commit=True)
        
        if "🌈" in card:
            await handle_wild_color_card(c, state, room_id, p_idx, opp_id, p_name, hand, card, discard_pile, room)
            return
            
        elif "🔥" in card:
            await handle_wild_draw4_card(
                c, state, room_id, p_idx, opp_id, p_name, card, discard_pile, hand, room
            )
            return
        
        if "🚫" in card or "🔄" in card:
            symbol = "🚫" if "🚫" in card else "🔄"
            next_turn = p_idx
            alerts[c.from_user.id] = f"{symbol} منعت الخصم! الدور بقى إلك."
            alerts[opp_id] = f"{symbol} {p_name} منعك من اللعب!"
        elif "💧" in card:
            next_turn = await handle_draw1_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts)
        elif "🌊" in card:
            next_turn = await handle_draw2_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts)
        elif "+2" in card:
            next_turn = await handle_colored_draw2_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts)

        db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
        current_id = c.from_user.id if next_turn == p_idx else opp_id
        check_p = db_query("SELECT hand FROM room_players WHERE user_id = %s", (current_id,))
        current_hand = safe_load(check_p[0]['hand']) if check_p else []
        can_play_now = False
        for c_check in current_hand:
            if check_validity(c_check, card, new_color):
                can_play_now = True
                break
        if not can_play_now:
            cancel_timer(room_id)
            cancel_auto_draw_task(room_id)
            msg = "⚠️ ما عندك ورقة مناسبة! راح اسحبلك تلقائياً بعد 5 ثواني..."
            await refresh_ui_2p(room_id, c.bot, {current_id: msg})
            for idx2, p2 in enumerate(players):
                if p2['user_id'] == current_id:
                    auto_draw_tasks[room_id] = asyncio.create_task(background_auto_draw(room_id, c.bot, idx2))
                    break
            return

        await refresh_ui_2p(room_id, c.bot, alerts)
        
    except Exception as e:
        print(f"Error in handle_play: {e}")
        await c.answer("⚠️ حدث خطأ بسيط، حاول مرة أخرى", show_alert=True)

@router.callback_query(GameStates.choosing_color, F.data.startswith("cl_"))
async def handle_color(c: types.CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        room_id = data.get('room_id')
        card = data.get('card_played')
        p_idx = data.get('p_idx')
        chosen_color = c.data.split("_")[1]
        
        # إلغاء التايمر أولاً
        task = color_timers.pop(room_id, None)
        if task and not task.done():
            task.cancel()
            await asyncio.sleep(0.1)
        
        # حذف رسالة العداد
        cd = color_countdown_msgs.pop(room_id, None)
        if cd:
            try: 
                await cd['bot'].delete_message(cd['chat_id'], cd['msg_id'])
            except: 
                pass
        
        # إزالة البيانات المعلقة
        pending_color_data.pop(room_id, None)
        
        if room_id in color_timed_out:
            color_timed_out.discard(room_id)
            await state.clear()
            return
        
        players = get_ordered_players(room_id)
        opp_id = players[(p_idx + 1) % 2]['user_id']
        p_name = players[p_idx].get('player_name') or "لاعب"
        
        # إذا كانت الورقة من نوع 🔥 جوكر+4
        if "🔥" in card:
            kb = [[
                InlineKeyboardButton(text="🕵️‍♂️ أتحداك", callback_data=f"rs_y_{room_id}_{data.get('prev_color')}_{chosen_color}"),
                InlineKeyboardButton(text="✅ قبول", callback_data=f"rs_n_{room_id}_{chosen_color}")
            ]]
            msg_sent = await c.bot.send_message(
                opp_id, 
                f"🚨 {p_name} لعب 🔥 +4 وغير اللون لـ {chosen_color}!", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
            cd_msg = await c.bot.send_message(
                opp_id, 
                "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢"
            )
            challenge_countdown_msgs[room_id] = {'bot': c.bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
            challenge_timers[room_id] = asyncio.create_task(
                challenge_timeout_2p(room_id, c.bot)
            )
            await c.message.edit_text("⏳ بانتظار الخصم...")
            await state.clear()
            return
        
        penalty = 1 if "💧" in card else (2 if "🌊" in card else 0)
        room_res = db_query("SELECT deck FROM rooms WHERE room_id = %s", (room_id,))[0]
        deck = safe_load(room_res['deck'])
        alerts = {}
        
        if penalty > 0:
            opp_h = safe_load(players[(p_idx + 1) % 2]['hand'])
            for _ in range(penalty):
                if deck: 
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", 
                    (json.dumps(opp_h), opp_id), commit=True)
            next_turn = p_idx
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} وسحبك {penalty} ورقة والدور رجع له!"
            alerts[c.from_user.id] = f"🎨 اخترت اللون {chosen_color} وسحب الخصم {penalty} ورقة!"
        else:
            next_turn = (p_idx + 1) % 2
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} والدور صار لك!"
            alerts[c.from_user.id] = f"🎨 اخترت اللون {chosen_color} والدور انتقل للخصم!"
        
        # تحديث قاعدة البيانات
        db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s", 
                (f"{card} {chosen_color}", chosen_color, next_turn, json.dumps(deck), room_id), commit=True)
        
        await state.clear()
        
        # تحديث الواجهة
        await refresh_ui_2p(room_id, c.bot, alerts)
        
    except Exception as e: 
        print(f"Color Error: {e}")


@router.callback_query(F.data.startswith("challenge_"))
async def handle_challenge_decision(c: types.CallbackQuery):
    try:
        data = c.data.split("_")
        decision = data[1]
        room_id = data[2]

        # إلغاء المؤقتات
        if room_id in challenge_timers:
            challenge_timers[room_id].cancel()
            del challenge_timers[room_id]
        if room_id in challenge_countdown_msgs:
            cd_info = challenge_countdown_msgs.pop(room_id)
            try: await c.bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except: pass

        pending = pending_color_data.pop(room_id, None)
        if not pending or pending.get('type') != 'challenge':
            return await c.answer("⚠️ انتهت صلاحية التحدي.", show_alert=True)
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة.", show_alert=True)
        room = room_data[0]
        players = get_ordered_players(room_id)
        p_idx = pending['p_idx']
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']
        user_id = players[p_idx]['user_id']

        deck = safe_load(room['deck'])
        if decision == "n":
            opp_hand = safe_load(players[opp_idx]['hand'])
            for _ in range(4):
                if deck: opp_hand.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET deck = %s, turn_index = %s, current_color = 'ANY' WHERE room_id = %s", (json.dumps(deck), p_idx, room_id), commit=True)
            await c.bot.send_message(opp_id, "✅ قبلت السحب! سحبت 4 ورقات.")
            await c.bot.send_message(user_id, "✅ خصمك قبل السحب! دورك الآن ويمكنك لعب أي لون.")
        else:
            p_hand = safe_load(players[p_idx]['hand'])
            prev_top_card = pending.get('prev_top_card', room['top_card'])
            prev_color = pending.get('prev_color', room['current_color'])
            cheated = False
            for check_card in p_hand:
                if any(x in check_card for x in ["🌈", "🔥", "💧", "🌊"]):
                    continue
                if check_validity(check_card, prev_top_card, prev_color):
                    cheated = True
                    break
            if cheated:
                for _ in range(6):
                    if deck: p_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(p_hand), user_id), commit=True)
                db_query("UPDATE rooms SET deck = %s, turn_index = %s WHERE room_id = %s", (json.dumps(deck), opp_idx, room_id), commit=True)
                await c.bot.send_message(user_id, "🕵️‍♂️ كشف الغش! سحبت 6 أوراق عقوبة والخصم يأخذ الدور!")
                await c.bot.send_message(opp_id, "✅ نجح التحدي! الخصم كان لديه ورقة مناسبة غير الجوكر.")
            else:
                opp_hand = safe_load(players[opp_idx]['hand'])
                for _ in range(6):
                    if deck: opp_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
                db_query("UPDATE rooms SET deck = %s, turn_index = %s, current_color = 'ANY' WHERE room_id = %s", (json.dumps(deck), p_idx, room_id), commit=True)
                await c.bot.send_message(opp_id, "❌ فشل التحدي! أنت تسحب 6 أوراق.")
                await c.bot.send_message(user_id, "🎯 الخصم فشل في التحدي – العب بأي لون.")

        try: await c.message.delete()
        except: pass
        await refresh_ui_2p(room_id, c.bot)
    except Exception as e:
        print(f"[handle_challenge_decision] Error: {e}")
        await c.answer("⚠️ خطأ أثناء معالجة قرار التحدي.", show_alert=True)


@router.callback_query(F.data.startswith("un_"))
async def handle_uno(c: types.CallbackQuery):
    try:
        room_id = c.data.split("_")[1]
        db_query("UPDATE room_players SET said_uno = TRUE WHERE room_id = %s AND user_id = %s", (room_id, c.from_user.id), commit=True)
        players = get_ordered_players(room_id)
        opp = next((p for p in players if p['user_id'] != c.from_user.id), None)
        me = next((p for p in players if p['user_id'] == c.from_user.id), None)
        p_name = me.get('player_name') if me else "لاعب"
        await c.answer()
        alerts = {c.from_user.id: "✅ صحت اونو بنجاح وأنت في أمان."}
        if opp:
            alerts[opp['user_id']] = f"🚨 {p_name} صاح اونو! بقتله ورقة وحدة وهو في أمان."
        try:
            if IMG_UNO_SAFE_ME and IMG_UNO_SAFE_ME != "123":
                await _send_photo_then_schedule_delete(c.bot, c.from_user.id, IMG_UNO_SAFE_ME)
            if opp and IMG_UNO_SAFE_OPP and IMG_UNO_SAFE_OPP != "123":
                await _send_photo_then_schedule_delete(c.bot, opp['user_id'], IMG_UNO_SAFE_OPP)
        except: pass
        await refresh_ui_2p(room_id, c.bot, alerts)
    except Exception as e: print(f"Uno Error: {e}")


@router.callback_query(F.data.startswith("ct_"))
async def handle_catch(c: types.CallbackQuery):
    try:
        room_id = c.data.split("_")[1]
        players = get_ordered_players(room_id)
        opp = next(p for p in players if p['user_id'] != c.from_user.id)
        opp_h = safe_load(opp['hand'])
        me = next((p for p in players if p['user_id'] == c.from_user.id), None)
        p_name = me.get('player_name') if me else "لاعب"
        opp_name = opp.get('player_name') or "لاعب"
        if len(opp_h) == 1 and not str(opp.get('said_uno')).lower() in ['true', '1']:
            room_data = db_query("SELECT deck FROM rooms WHERE room_id = %s", (room_id,))[0]
            deck = safe_load(room_data['deck'])
            for _ in range(2):
                if deck: opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_h), opp['user_id']), commit=True)
            db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
            await c.answer()
            try:
                if IMG_CATCH_SUCCESS and IMG_CATCH_SUCCESS != "123":
                    await _send_photo_then_schedule_delete(c.bot, c.from_user.id, IMG_CATCH_SUCCESS)
                if IMG_CATCH_PENALTY and IMG_CATCH_PENALTY != "123":
                    await _send_photo_then_schedule_delete(c.bot, opp['user_id'], IMG_CATCH_PENALTY)
            except: pass
            alerts = {
                c.from_user.id: f"🪤 صدت {opp_name}! سحب ورقتين لأنه نسي الاونو.",
                opp['user_id']: f"⚠️ {p_name} صادك! سحبت ورقتين لأنك نسيت تصيح اونو!"
            }
            await refresh_ui_2p(room_id, c.bot, alerts)
        else:
            await c.answer("❌ ما تگدر تصيده حالياً!")
    except Exception as e: print(f"Catch Error: {e}")


@router.callback_query(F.data.startswith("ex_"))
async def ask_exit(c: types.CallbackQuery):
    rid = c.data.split("_")[1]
    kb = [[InlineKeyboardButton(text="✅ نعم", callback_data=f"cf_ex_{rid}"), InlineKeyboardButton(text="❌ لا", callback_data=f"cn_ex_{rid}")]]
    await c.message.edit_text("🚪 هل أنت متأكد من الانسحاب؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("cf_ex_"))
async def confirm_exit(c: types.CallbackQuery):
    rid = c.data.split("_")[2]
    try: await c.message.delete()
    except: pass
    cancel_timer(rid)
    players = get_ordered_players(rid)
    room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (rid,))
    room = room_data[0] if room_data else {'max_players': 2, 'score_limit': 0}
    me = next((x for x in players if x['user_id'] == c.from_user.id), None)
    leave_name = me.get('player_name') if me else "لاعب"
    from handlers.common import create_replay_session, build_game_end_keyboard
    exit_summary = f"🚪 {leave_name} انسحب، تم إلغاء اللعبة."
    replay_id = create_replay_session(players, room, '2p', exit_summary)
    for p in players:
        end_kb = build_game_end_keyboard(replay_id, p['user_id'])
        await c.bot.send_message(p['user_id'], exit_summary, reply_markup=end_kb)
    db_query("DELETE FROM rooms WHERE room_id = %s", (rid,), commit=True)

@router.callback_query(F.data.startswith("cn_ex_"))
async def cancel_exit(c: types.CallbackQuery):
    rid = c.data.split("_")[2]
    try:
        await c.message.delete()
    except:
        pass
    await refresh_ui_2p(rid, c.bot)

@router.callback_query(F.data.startswith("pass_"))
async def process_pass_turn(c: types.CallbackQuery):
    try:
        room_id = c.data.split("_")[1]
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data: return await c.answer("⚠️ الغرفة غير موجودة")
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']
        if c.from_user.id != players[curr_idx]['user_id']:
            return await c.answer("❌ مو دورك تمرر!", show_alert=True)
        next_turn = (curr_idx + 1) % 2
        db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
        p_name = players[curr_idx].get('player_name') or "لاعب"
        opp_id = players[next_turn]['user_id']
        alerts = {opp_id: f"➡️ {p_name} مرر الدور، هسة دورك!"}
        await refresh_ui_2p(room_id, c.bot, alerts)
        await c.answer("تم تمرير الدور 👍")
    except Exception as e:
        print(f"Error in process_pass_turn: {e}")
        await c.answer("⚠️ حدث خطأ")

@router.callback_query(F.data.startswith("rs_"))
async def handle_challenge(c: types.CallbackQuery):
    """
    معالجة رد الخصم على تحدي الجوكر +4 بعد اختيار اللون.
    """
    try:
        parts = c.data.split("_")
        # إلغاء مؤقت التحدي الخاص بهذا السيناريو
        cancel_challenge_timer(parts[2])

        decision = parts[1]          # y أو n
        room_id = parts[2]

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة", show_alert=True)
        room = room_data[0]

        players = get_ordered_players(room_id)
        p_idx = room['turn_index']          # اللاعب الحالي (الذي لعب +4)
        opp_idx = (p_idx + 1) % 2
        deck = safe_load(room['deck'])
        alerts = {}

        if decision == "n":
            # الخصم قبل السحب
            opp_h = safe_load(players[opp_idx]['hand'])
            for _ in range(4):
                if deck:
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                     (json.dumps(opp_h), players[opp_idx]['user_id']), commit=True)

            next_turn = p_idx
            final_col = parts[3]   # اللون المختار

            alerts[players[p_idx]['user_id']] = "✅ الخصم قبل السحب والدور رجع الك!"
            alerts[players[opp_idx]['user_id']] = "📥 قبلت السحب وسحبت 4 ورقات وعبر دورك."

        else:  # decision == "y" (تحدي)
            prev_col = parts[3]     # اللون السابق قبل لعب +4
            chosen_col = parts[4]   # اللون الجديد الذي اختاره اللاعب

            # التحقق من غش اللاعب (هل كانت لديه ورقة مناسبة قبل لعب +4؟)
            p_hand = safe_load(players[p_idx]['hand'])
            cheated = False
            for card in p_hand:
                # نتجاهل الجوكرات لأنها مسموحة دائماً
                if any(x in card for x in ["🌈", "🔥", "💧", "🌊"]):
                    continue
                # نتحقق من صلاحية الورقة مقارنة بالورقة السابقة ولونها
                if check_validity(card, room['top_card'], prev_col):
                    cheated = True
                    break

            if cheated:
                # اللاعب غش → يسحب 6 ورقات والدور يذهب للخصم
                for _ in range(6):
                    if deck:
                        p_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                         (json.dumps(p_hand), players[p_idx]['user_id']), commit=True)
                next_turn = opp_idx
                alerts[players[p_idx]['user_id']] = "🕵️‍♂️ كشفك الخصم! سحبت 6 ورقات عقوبة."
                alerts[players[opp_idx]['user_id']] = "✅ نجح التحدي! الخصم كان يغش وسحب 6 ورقات."
            else:
                # اللاعب لم يغش → الخصم يسحب 6 ورقات والدور يبقى للاعب
                opp_h = safe_load(players[opp_idx]['hand'])
                for _ in range(6):
                    if deck:
                        opp_h.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                         (json.dumps(opp_h), players[opp_idx]['user_id']), commit=True)
                next_turn = p_idx
                alerts[players[p_idx]['user_id']] = "❌ فشل تحدي الخصم وسحب 6 ورقات! الدور الك."
                alerts[players[opp_idx]['user_id']] = "❌ فشل التحدي! سحبت 6 ورقات."
            final_col = chosen_col

        # تحديث الغرفة: كومة السحب، الدور، اللون الحالي، والورقة العليا
        db_query("""
            UPDATE rooms 
            SET deck = %s, turn_index = %s, current_color = %s, top_card = %s
            WHERE room_id = %s
        """, (json.dumps(deck), next_turn, final_col, f"🔥 جوكر+4 {final_col}", room_id), commit=True)

        # حذف رسالة التحدي
        try:
            await c.message.delete()
        except:
            pass

        # تحديث واجهة جميع اللاعبين
        await refresh_ui_2p(room_id, c.bot, alerts)

    except Exception as e:
        print(f"Challenge Error (rs_): {e}")
        await c.answer("⚠️ حدث خطأ أثناء معالجة التحدي", show_alert=True)

