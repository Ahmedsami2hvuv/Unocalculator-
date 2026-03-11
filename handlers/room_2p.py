########## استيرادات ##########
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db_query
from config import IMG_UNO_SAFE_ME, IMG_UNO_SAFE_OPP, IMG_CATCH_SUCCESS, IMG_CATCH_PENALTY
import json, random, asyncio, uuid


async def _send_message_then_delete(bot, chat_id, text, delete_after_seconds=5, **kwargs):
    """استيراد كسول لتجنب استيراد دائري مع common (يلزم لـ play_vs_bot -> start_new_round)."""
    from handlers.common import send_message_then_delete as _fn
    return await _fn(bot, chat_id, text, delete_after_seconds=delete_after_seconds, **kwargs)


from collections import Counter

########## المتغيرات العامة ##########
router = Router()
BOT_USER_ID = -1
turn_timers = {}
TURN_TIMEOUT = 20
countdown_msgs = {}
auto_draw_tasks = {}
player_ui_msgs = {} # المفتاح: user_id, القيمة: {'info': msg_id, 'buttons': msg_id}
challenge_timers = {}
challenge_countdown_msgs = {}
color_timers = {}
color_countdown_msgs = {}
pending_color_data = {}
color_timed_out = set()
temp_messages = {} # المفتاح: user_id, القيمة: list of message_ids

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
                      deck.append("💧 +1") # جوكر +1 السابق - الآن ورقة أكشن عادية
                      deck.append("🌊 +2") # جوكر +2 السابق - الآن ورقة أكشن عادية

                      # الجوكرات الحقيقية (التي تفتح قائمة ألوان أو تحدٍ)
                      deck.extend(["🔥 جوكر+4"] * 4) # جوكر +4 مع تحدي
                      deck.extend(["🌈 جوكر ألوان"] * 4) # جوكر ألوان فقط

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

def ensure_deck_from_discard(room_id, room):
                      """إذا كومة السحب فارغة، خذ كل الأوراق النازلة واخلطها لتصبح كومة سحب جديدة. يُرجع قائمة deck."""
                      deck = safe_load(room.get('deck', '[]'))
                      if deck:
                          return deck
                      discard = safe_load(room.get('discard_pile', '[]'))
                      if not discard:
                          return []
                      new_deck = list(discard)
                      random.shuffle(new_deck)
                      db_query("UPDATE rooms SET deck = %s, discard_pile = '[]' WHERE room_id = %s", (json.dumps(new_deck), room_id), commit=True)
                      return new_deck


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
                      if "🌈" in card: # جوكر ألوان دائمًا مسموح
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

                          # إخطار الجميع (تُحذف بعد 5 ثواني) — لا ترسل للبوت
                          if opp_id != BOT_USER_ID:
                              await _send_message_then_delete(bot, opp_id, "⏰ انتهى الوقت! تم قبول السحب تلقائياً (سحبت 4 ورقات).", delete_after_seconds=5)
                          if players[p_idx]['user_id'] != BOT_USER_ID:
                              await _send_message_then_delete(bot, players[p_idx]['user_id'], "تم قبول السحب افتراضيًا. يمكنك اللعب الآن بأي لون.", delete_after_seconds=5)

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
                                  continue  # لا تتوقف، استمر بالعد

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
                          deck = ensure_deck_from_discard(room_id, room)
                          if not deck:
                              next_turn = (expected_turn + 1) % 2
                              db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
                              turn_timers.pop(room_id, None)
                              msgs = {p_id: "⏰ انتهى وقتك! كومة السحب فارغة فمرّ دورك.", opp_id: f"⏰ {p_name} مرّ دوره (كومة السحب فارغة)."}
                              await refresh_ui_2p(room_id, bot, msgs)
                              return
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
            try:
                await bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except:
                pass

        color_timers.pop(room_id, None)
        pdata = pending_color_data.pop(room_id, None)
        if not pdata:
            return

        color_timed_out.add(room_id)
        card = pdata['card_played']
        p_idx = pdata['p_idx']
        prev_color = pdata['prev_color']
        chosen_color = random.choice(['🔴', '🔵', '🟡', '🟢'])

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return
        room = room_data[0]
        if room['status'] != 'playing':
            return

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
            cd_msg = await _send_message_then_delete(bot, opp_id, "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢", delete_after_seconds=5)
            if cd_msg:
                challenge_countdown_msgs[room_id] = {'bot': bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
                challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, bot))
            await _send_message_then_delete(bot, player_id, f"⏰ انتهى الوقت! تم اختيار اللون {chosen_color} تلقائياً. بانتظار رد الخصم...", delete_after_seconds=5)
            return

        deck = safe_load(room['deck'])
        alerts = {}
        penalty = 1 if "💧" in card else (2 if "🌊" in card else 0)
        next_turn = p_idx  # القيمة الافتراضية (للجوكرات ذات العقوبة)

        if penalty > 0:
            if not deck:
                deck = []  # لا ننشئ أوراقاً جديدة
            opp_h = safe_load(players[opp_idx]['hand'])
            for _ in range(penalty):
                if deck:
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_h), opp_id), commit=True)
            alerts[opp_id] = f"⏰ {p_name} ما اختار اللون بالوقت! تم اختيار {chosen_color} تلقائياً وسحبك {penalty} ورقة والدور رجع له!"
            alerts[player_id] = f"⏰ انتهى الوقت! تم اختيار اللون {chosen_color} تلقائياً."
        else:
            # جوكر ألوان (🌈): الدور يرجع للاعب نفسه (2 لاعب)
            next_turn = p_idx
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} — دورك بعد ما يلعب."
            alerts[player_id] = f"🎨 اخترت اللون {chosen_color} والدور بقى إلك!"

        db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
            (f"{card} {chosen_color}", chosen_color, next_turn, json.dumps(deck), room_id), commit=True)

        turn_timers.pop(room_id, None)
        countdown_msgs.pop(room_id, None)
        await refresh_ui_2p(room_id, bot, alerts)

    except asyncio.CancelledError:
        cd_info = color_countdown_msgs.get(room_id)
        if cd_info:
            try:
                await bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except:
                pass
        raise
    except Exception as e:
        print(f"Color timer error 2p: {e}")


async def background_auto_draw(room_id, bot, curr_idx):
    """سحب تلقائي بعد 5 ثوانٍ مع عدّ تنازلي يتحرك في رسالة منفصلة."""
    countdown_msg_id = None
    countdown_chat_id = None
    try:
        # لا نستدعي cancel_auto_draw_task هنا لأننا نحن المهمة الحالية — إلغاؤها يلغي السحب التلقائي

        players = get_ordered_players(room_id)
        if curr_idx >= len(players):
            return
        p_id = players[curr_idx]['user_id']
        p_name = players[curr_idx].get('player_name') or "لاعب"

        # تحديث واجهة اللعب مرة واحدة بالتنبيه
        await send_or_update_game_ui(
            room_id, bot, p_id,
            remaining_seconds=5,
            alert_text="⏳ ما عندك ورقة مناسبة! راح اسحبلك تلقائياً..."
        )

        # رسالة منفصلة للعدّ التنازلي (5→4→3→2→1) كي تتحرك دون تعديل رسالة اللعب
        for sec in range(5, 0, -1):
            try:
                txt = f"⏳ السحب التلقائي خلال {sec} ثواني..."
                if countdown_msg_id and countdown_chat_id:
                    await bot.edit_message_text(
                        chat_id=countdown_chat_id,
                        message_id=countdown_msg_id,
                        text=txt
                    )
                else:
                    msg = await bot.send_message(p_id, txt)
                    countdown_msg_id = msg.message_id
                    countdown_chat_id = p_id
            except Exception:
                if not countdown_msg_id:
                    msg = await bot.send_message(p_id, f"⏳ السحب التلقائي خلال {sec} ثواني...")
                    countdown_msg_id = msg.message_id
                    countdown_chat_id = p_id
            await asyncio.sleep(1)

        # حذف رسالة العدّ
        if countdown_msg_id and countdown_chat_id:
            try:
                await bot.delete_message(countdown_chat_id, countdown_msg_id)
            except Exception:
                pass

        # التحقق من أن اللاعب لا يزال في نفس الدور
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            await refresh_ui_2p(room_id, bot)
            return
        room = room_data[0]
        if room['turn_index'] != curr_idx:
            await refresh_ui_2p(room_id, bot)
            return

        deck = ensure_deck_from_discard(room_id, room)
        if not deck:
            next_turn = (curr_idx + 1) % 2
            db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
            await refresh_ui_2p(room_id, bot, {p_id: "📥 كومة السحب فارغة فمرّ دورك."})
            return
        curr_hand = safe_load(players[curr_idx]['hand'])
        new_card = deck.pop(0)
        curr_hand.append(new_card)

        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
            (json.dumps(curr_hand), p_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s",
            (json.dumps(deck), room_id), commit=True)

        if check_validity(new_card, room['top_card'], room['current_color']):
            await refresh_ui_2p(room_id, bot, {p_id: f"✅ سحبت ({new_card}) وتشتغل! الك 20 ثانية."})
        else:
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
        if countdown_msg_id and countdown_chat_id:
            try:
                await bot.delete_message(countdown_chat_id, countdown_msg_id)
            except Exception:
                pass
        raise
    except Exception as e:
        print(f"Error in background_auto_draw: {e}")
        try:
            await refresh_ui_2p(room_id, bot)
        except Exception:
            pass
    finally:
        if room_id in auto_draw_tasks:
            try:
                del auto_draw_tasks[room_id]
            except Exception:
                pass

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
    if not room_data:
        return
    room = room_data[0]
    players = get_ordered_players(room_id)
    user_id = players[p_idx]['user_id']

    deck = ensure_deck_from_discard(room_id, room)
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
        if not room_data:
            return
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']

        current_player = next((p for p in players if p['user_id'] == user_id), None)
        if not current_player:
            return

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

        # 2. بناء شريط الوقت (🟢🟡🔴) — في وضع التدريب لا يوجد توقيت
        if is_my_turn:
            if room.get("is_training"):
                info_text += "\n──────────────\n📚 تدريب — دورك (بدون توقيت) 👍🏻"
            else:
                remaining = remaining_seconds if remaining_seconds is not None else 20
                total_steps = 10
                steps_left = (remaining + 1) // 2
                bar_parts = []
                for s in range(total_steps):
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
                kb.append(row)
                row = []
        if row:
            kb.append(row)

        controls = []
        if is_my_turn:
            if len(hand) == 2 and any(check_validity(c, room['top_card'], room['current_color']) for c in hand):
                controls.append(InlineKeyboardButton(text="🚨 اونو!", callback_data=f"un_{room_id}"))

        # منطق الصيدة: لا نعرض الزر عندما الخصم بوت (البوت ينفّذ الصيدة تلقائياً في دوره)
        opp = players[1] if players[0]['user_id'] == user_id else players[0]
        if opp['user_id'] != BOT_USER_ID:
            opp_h = safe_load(opp.get('hand', '[]'))
            if len(opp_h) == 1 and not str(opp.get('said_uno', 'false')).lower() in ['true', '1']:
                controls.append(InlineKeyboardButton(text="🪤 صيدة!", callback_data=f"ct_{room_id}"))

        if controls:
            kb.append(controls)
        kb.append([InlineKeyboardButton(text="🚪 انسحاب", callback_data=f"ex_{room_id}")])
        markup = InlineKeyboardMarkup(inline_keyboard=kb)

        # 4. التحديث الذكي (الجزء الأهم لثبات الرسالة)
        old_msg_id = player_ui_msgs.get(user_id, {}).get('game_ui')

        parse_kw = {"parse_mode": "Markdown"} if "**" in info_text else {}
        if old_msg_id:
            try:
                await bot.edit_message_text(
                    text=info_text,
                    chat_id=user_id,
                    message_id=old_msg_id,
                    reply_markup=markup,
                    **parse_kw
                )
                return
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    return
                pass

        new_msg = await bot.send_message(user_id, info_text, reply_markup=markup, **parse_kw)
        player_ui_msgs.setdefault(user_id, {})['game_ui'] = new_msg.message_id

    except Exception as e:
        print(f"UI Error: {e}")


async def refresh_ui_2p(room_id, bot, alert_msg_dict=None):
    """تحديث واجهة المستخدم بالكامل (رسالة واحدة موحدة تحتوي على المعلومات والأزرار)."""
    try:
        cancel_timer(room_id)

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']
        curr_p = players[curr_idx]
        is_vs_bot = any(p['user_id'] == BOT_USER_ID for p in players)

        for i, p in enumerate(players):
            user_id = p['user_id']
            if user_id == BOT_USER_ID:
                continue
            is_my_turn = (i == curr_idx)
            alert_text = alert_msg_dict.get(user_id) if alert_msg_dict else None

            if is_my_turn and room_id in countdown_msgs:
                remaining = 20
                await send_or_update_game_ui(room_id, bot, user_id, remaining_seconds=remaining, alert_text=alert_text)
            else:
                await send_or_update_game_ui(room_id, bot, user_id, alert_text=alert_text)

        if is_vs_bot and curr_p['user_id'] == BOT_USER_ID:
            asyncio.create_task(_bot_play_turn_delayed(room_id, bot))
            return

        curr_hand = safe_load(curr_p['hand'])
        is_playable = any(check_validity(c, room['top_card'], room['current_color']) for c in curr_hand)

        if room.get("is_training"):
            if curr_p["user_id"] != BOT_USER_ID:
                from handlers.training import send_training_plan
                valid_list = [c for c in curr_hand if check_validity(c, room['top_card'], room['current_color'])]
                asyncio.create_task(send_training_plan(
                    room_id, bot, curr_p["user_id"], curr_hand,
                    room['top_card'], room['current_color'], valid_list
                ))
            # تدريب: بدون توقيت 20 ثانية، لكن السحب التلقائي (5 ثواني) يشتغل
            if not is_playable:
                cancel_auto_draw_task(room_id)
                if room_id not in auto_draw_tasks or auto_draw_tasks[room_id].done():
                    auto_draw_tasks[room_id] = asyncio.create_task(background_auto_draw(room_id, bot, curr_idx))
            return

        if not is_playable:
            cancel_auto_draw_task(room_id)
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
            if exclude_ids and msg_id in exclude_ids:
                continue
            try:
                await bot.delete_message(user_id, msg_id)
            except:
                pass
        temp_messages[user_id] = [msg_id for msg_id in temp_messages[user_id]
            if not exclude_ids or msg_id not in exclude_ids]

async def send_temp_message_and_delete(bot, user_id, text, delay=1.5):
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except:
        pass

##### دالة حذف رسالة عداد #####��
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

async def handle_draw1_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile):
    """جوكر +1 (💧): تلعبها أي وقت، الخصم يسحب ورقة واحدة، والدور يرجع للاعب (2 لاعب)."""
    next_turn = p_idx  # الدور يبقى عند اللاعب
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = ensure_deck_from_discard(room_id, room)
    opp_hand = safe_load(players[opp_idx]['hand'])
    drawn_cards = []
    for _ in range(1):
        if deck:
            drawn_cards.append(deck.pop(0))
    if drawn_cards:
        opp_hand.extend(drawn_cards)
        db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
            (json.dumps(opp_hand), opp_id), commit=True)
        db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
        alerts[opp_id] = f"💧 {p_name} لعب جوكر +1 وسحبك ورقة! 🎯"
    alerts[c.from_user.id] = f"💧 لعبت جوكر +1 وسحبت الخصم ورقة! الدور بقى إلك ✅"
    db_query("UPDATE rooms SET top_card = %s, current_color = %s, discard_pile = %s WHERE room_id = %s",
        (card, "ANY", json.dumps(discard_pile), room_id), commit=True)
    return next_turn

async def handle_draw2_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile):
    """جوكر +2 (🌊): تلعبها أي وقت، الخصم يسحب ورقتين، والدور يرجع للاعب (2 لاعب)."""
    next_turn = p_idx
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = ensure_deck_from_discard(room_id, room)
    opp_hand = safe_load(players[opp_idx]['hand'])
    drawn_cards = []
    for _ in range(2):
        if not deck:
            room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
            deck = ensure_deck_from_discard(room_id, room)
        if deck:
            drawn_cards.append(deck.pop(0))
    if drawn_cards:
        opp_hand.extend(drawn_cards)
    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
        (json.dumps(opp_hand), opp_id), commit=True)
    db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
    alerts[opp_id] = f"🌊 {p_name} لعب جوكر +2 وسحبك ورقتين! 🎯"
    alerts[c.from_user.id] = f"🌊 لعبت جوكر +2 وسحبت الخصم ورقتين! الدور بقى إلك ✅"
    db_query("UPDATE rooms SET top_card = %s, current_color = %s, discard_pile = %s WHERE room_id = %s",
        (card, "ANY", json.dumps(discard_pile), room_id), commit=True)
    return next_turn


async def handle_colored_draw2_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile):
    """ورقة +2 الملونة: تسحب الخصم ورقتين والدور يبقى للاعب مع تثبيت اللون."""
    next_turn = p_idx
    p_name = players[p_idx].get('player_name') or "لاعب"
    deck = ensure_deck_from_discard(room_id, room)
    if not deck:
        deck = []
    opp_hand = safe_load(players[opp_idx]['hand'])
    for _ in range(2):
        if not deck:
            room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
            deck = ensure_deck_from_discard(room_id, room)
        if deck:
            opp_hand.append(deck.pop(0))
    card_color = card.split()[0]
    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
    db_query("""UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s, discard_pile = %s WHERE room_id = %s""",
        (card, card_color, next_turn, json.dumps(deck), json.dumps(discard_pile), room_id), commit=True)
    alerts[opp_id] = f"{card_color} {p_name} لعب +2 ملونة وسحبك ورقتين! 🎯"
    alerts[c.from_user.id] = f"✅ لعبت +2 ملونة، سحبت الخصم وباقي دورك!"
    return next_turn

async def handle_skip_card(c, room_id, p_idx, opp_id, p_name, card, next_turn, alerts):
    """معالجة ورقة منع (🚫) - تمنع اللاعب التالي"""
    next_turn = p_idx # الدور يرجع للاعب نفسه
    alerts[opp_id] = f"🚫 {p_name} لعب ورقة منع!"
    alerts[c.from_user.id] = f"🚫 لعبت ورقة منع!"
    return next_turn

async def handle_reverse_card(c, room_id, p_idx, opp_id, p_name, card, next_turn, alerts):
    """معالجة ورقة عكس (🔄) - في 2 لاعبين ترجع الدور للاعب نفسه"""
    next_turn = p_idx # الدور يرجع للاعب نفسه
    alerts[opp_id] = f"🔄 {p_name} لعب ورقة عكس!"
    alerts[c.from_user.id] = f"🔄 لعبت ورقة عكس!"
    return next_turn

async def handle_wild_draw4_card(c, state: FSMContext, room_id, p_idx, opp_id, p_name, card, discard_pile, hand, room):
    """
    عند لعب جوكر +4: ترسل رسالة للخصم (هل تتحدى أم تقبل؟) وتمنع اللاعب الحالي من اللعب حتى يرد الخصم.
    """
    try:
        if opp_id == BOT_USER_ID:
            deck = ensure_deck_from_discard(room_id, room)
            players = get_ordered_players(room_id)
            opp_idx = (p_idx + 1) % 2
            bot_hand = safe_load(players[opp_idx]['hand'])
            for _ in range(4):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    bot_hand.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(bot_hand), BOT_USER_ID), commit=True)
            db_query("UPDATE rooms SET top_card = %s, discard_pile = %s, current_color = 'ANY', turn_index = %s, deck = %s WHERE room_id = %s",
                (card, json.dumps(discard_pile), p_idx, json.dumps(deck), room_id), commit=True)
            await _send_message_then_delete(c.bot, c.from_user.id, "🤖 البوت قبل السحب وسحب 4 ورقات. دورك!", delete_after_seconds=5)
            await refresh_ui_2p(room_id, c.bot)
            return
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
        await c.bot.send_message(
            opp_id,
            f"🔥 {p_name} لعب جوكر +4!\nهل تريد التحدي؟ لديك 20 ثانية للاختيار.",
            reply_markup=kb
        )
        cd_msg = await _send_message_then_delete(c.bot, opp_id, "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢", delete_after_seconds=5)
        if cd_msg:
            challenge_countdown_msgs[room_id] = {'bot': c.bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
            challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, c.bot))
        await c.answer("✅ بانتظار رد الخصم على جوكر +4، لا يمكنك اللعب الآن.", show_alert=True)
        await send_or_update_game_ui(room_id, c.bot, c.from_user.id, alert_text="🔥 لعبت جوكر +4!\nبانتظار رد الخصم.", remaining_seconds=None)
    except Exception as e:
        print(f"[handle_wild_draw4_card] Error: {e}")
        await c.answer("❌ حدث خطأ أثناء معالجة جوكر +4", show_alert=True)

async def _bot_play_turn_delayed(room_id, bot):
    await asyncio.sleep(1.5)
    await bot_play_turn(room_id, bot)


async def bot_play_turn(room_id, bot):
    """دور البوت: يختار ورقة صالحة أو يسحب، يحدّث الغرفة، ويحدّث الواجهة أو يرسل التحدي."""
    try:
        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data or room_data[0]['status'] != 'playing':
            return
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']
        if curr_idx >= len(players) or players[curr_idx]['user_id'] != BOT_USER_ID:
            return
        p_idx = curr_idx
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']
        bot_hand = safe_load(players[p_idx]['hand'])
        top_card = room['top_card']
        current_color = room['current_color']
        deck = ensure_deck_from_discard(room_id, room)
        if not deck:
            deck = []

        opp_hand = safe_load(players[opp_idx]['hand'])
        opp_said_uno = str(players[opp_idx].get('said_uno', False)).lower() in ['true', '1']
        if len(opp_hand) == 1 and not opp_said_uno:
            for _ in range(2):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    opp_hand.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s, said_uno = FALSE WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
            catch_msg = None
            try:
                catch_msg = await bot.send_message(opp_id, "🪤 **البوت صادك!** سحبت ورقتين لأنك نسيت تصيح اونو.\n⏳ اللعبة تكمل خلال 5 ثواني...", parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(5)
            if catch_msg:
                try:
                    await bot.delete_message(opp_id, catch_msg.message_id)
                except Exception:
                    pass
            await refresh_ui_2p(room_id, bot, {opp_id: "🪤 البوت صادك! سحبت ورقتين. دور البوت يلعب..."})
            room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
            if not room_data or room_data[0]['status'] != 'playing':
                return
            room = room_data[0]
            players = get_ordered_players(room_id)
            deck = ensure_deck_from_discard(room_id, room)
            bot_hand = safe_load(players[p_idx]['hand'])
            top_card = room['top_card']
            current_color = room['current_color']

        valid = [c for c in bot_hand if check_validity(c, top_card, current_color)]
        if room.get("is_training") and valid:
            # في وضع التدريب: لا نلعب ورقة تجعل البوت يربح (يده تصبح فارغة)
            winning_plays = [c for c in valid if len(bot_hand) == 1]
            valid_non_win = [c for c in valid if c not in winning_plays]
            if valid_non_win:
                valid = valid_non_win
        if not valid:
            no_card_msg = None
            try:
                no_card_msg = await bot.send_message(opp_id, "🤖 البوت ما عنده ورقة مناسبة. راح يسحب ورقة خلال 5 ثواني...", parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(5)
            if no_card_msg:
                try:
                    await bot.delete_message(opp_id, no_card_msg.message_id)
                except Exception:
                    pass
            if deck:
                new_card = deck.pop(0)
                bot_hand.append(new_card)
                db_query("UPDATE room_players SET hand = %s, said_uno = FALSE WHERE user_id = %s", (json.dumps(bot_hand), BOT_USER_ID), commit=True)
                db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
                if check_validity(new_card, top_card, current_color):
                    valid = [new_card]
            if not valid:
                next_turn = opp_idx
                db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
                await refresh_ui_2p(room_id, bot, {opp_id: "🤖 البوت سحب ورقة ومرر دوره. دورك!"})
                return

        card = random.choice(valid)
        bot_hand.remove(card)
        discard_pile = safe_load(room.get('discard_pile', '[]'))
        discard_pile.append(top_card)
        # البوت يصرّح أونو تلقائياً عندما يبقى له ورقة واحدة
        bot_said_uno = len(bot_hand) == 1
        db_query("UPDATE room_players SET hand = %s, said_uno = %s WHERE user_id = %s",
            (json.dumps(bot_hand), bot_said_uno, BOT_USER_ID), commit=True)
        db_query("UPDATE rooms SET discard_pile = %s WHERE room_id = %s", (json.dumps(discard_pile), room_id), commit=True)
        p_name = "البوت"

        if len(bot_hand) == 0:
            human_hand = safe_load(players[opp_idx]['hand'])
            points = calculate_points(human_hand)
            try:
                row = db_query("SELECT online_points FROM users WHERE user_id = %s", (opp_id,))
                cur = (row[0]['online_points'] or 0) if row else 0
                db_query("UPDATE users SET online_points = %s WHERE user_id = %s", (cur + points, opp_id), commit=True)
            except Exception:
                pass
            try:
                from badges import badge_on_loss
                badge_on_loss(opp_id)
            except Exception:
                pass
            win_text = "🏆 **البوت فاز بالجولة!** 🏆\n📊 الخصم (أنت) كان لديه ورق بقيمة " + str(points) + " نقطة."
            db_query("DELETE FROM room_players WHERE room_id = %s", (room_id,), commit=True)
            db_query("DELETE FROM rooms WHERE room_id = %s", (room_id,), commit=True)
            from handlers.common import build_game_end_keyboard
            end_kb = build_game_end_keyboard(None, opp_id)
            try:
                await bot.send_message(opp_id, win_text, reply_markup=end_kb)
            except Exception:
                pass
            return

        chosen_color = None
        if "🌈" in card or "🔥" in card:
            colors_in_hand = [x.split()[0] for x in bot_hand if x.split()[0] in ['🔴', '🟡', '🟢', '🔵']]
            chosen_color = random.choice(['🔴', '🟡', '🟢', '🔵']) if not colors_in_hand else Counter(colors_in_hand).most_common(1)[0][0]

        if "🔥" in card:
            db_query("UPDATE rooms SET top_card = %s, current_color = %s WHERE room_id = %s",
                (f"{card} {chosen_color}", chosen_color, room_id), commit=True)
            pending_color_data[room_id] = {
                'card_played': card, 'p_idx': p_idx, 'opp_id': opp_id, 'p_name': p_name,
                'type': 'challenge', 'prev_top_card': top_card, 'prev_color': current_color,
            }
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🕵️‍♂️ أتحداك", callback_data=f"challenge_y_{room_id}"),
                 InlineKeyboardButton(text="✅ أقبل السحب", callback_data=f"challenge_n_{room_id}")]
            ])
            try:
                await bot.send_message(opp_id, f"🔥 {p_name} لعب جوكر +4 واختار اللون {chosen_color}! هل تريد التحدي؟", reply_markup=kb)
            except Exception:
                pass
            cd_msg = await _send_message_then_delete(bot, opp_id, "⏳ باقي 20 ثانية للرد", delete_after_seconds=5)
            if cd_msg:
                challenge_countdown_msgs[room_id] = {'bot': bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
                challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, bot))
            return

        # الجوكر وكل الأكشن (منع، تحويل، +2 ملونة): الدور يرجع للاعب اللي لعب (2 لاعب)
        is_action_or_joker = any(x in card for x in ["🌈", "🔥", "💧", "🌊", "🚫", "🔄"]) or ("+2" in card and len(card) > 2)
        next_turn = p_idx if is_action_or_joker else (p_idx + 1) % 2
        new_color = chosen_color if chosen_color else card.split()[0]
        alerts = {opp_id: f"🤖 {p_name} لعب {card}"}

        if "🌈" in card:
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s WHERE room_id = %s",
                (f"{card} {chosen_color}", chosen_color, next_turn, room_id), commit=True)
            alerts[opp_id] = f"🤖 {p_name} لعب جوكر ألوان واختار {chosen_color}. دور البوت مرة ثانية!"
        elif "🚫" in card or "🔄" in card:
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s WHERE room_id = %s",
                (card, new_color, next_turn, room_id), commit=True)
            alerts[opp_id] = f"🤖 {p_name} لعب {card}! دور البوت مرة ثانية."
        elif "💧" in card:
            for _ in range(1):
                if deck:
                    h_hand = safe_load(players[opp_idx]['hand'])
                    h_hand.append(deck.pop(0))
                    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(h_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
                (card, "ANY", next_turn, json.dumps(deck), room_id), commit=True)
            alerts[opp_id] = f"🤖 {p_name} لعب 💧 +1 وسحبك ورقة! دور البوت مرة ثانية."
        elif "🌊" in card:
            for _ in range(2):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    h_hand = safe_load(players[opp_idx]['hand'])
                    h_hand.append(deck.pop(0))
                    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(h_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
                (card, "ANY", next_turn, json.dumps(deck), room_id), commit=True)
            alerts[opp_id] = f"🤖 {p_name} لعب 🌊 +2 وسحبك ورقتين! دور البوت مرة ثانية."
        elif "+2" in card and card.split()[0] in ['🔴', '🟡', '🟢', '🔵']:
            for _ in range(2):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    h_hand = safe_load(players[opp_idx]['hand'])
                    h_hand.append(deck.pop(0))
                    db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(h_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
                (card, new_color, next_turn, json.dumps(deck), room_id), commit=True)
            alerts[opp_id] = f"🤖 {p_name} لعب +2 ملونة وسحبك ورقتين!"
        else:
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s WHERE room_id = %s",
                (card, new_color, next_turn, room_id), commit=True)

        await refresh_ui_2p(room_id, bot, alerts)
    except Exception as e:
        print(f"Error in bot_play_turn: {e}")
        try:
            await refresh_ui_2p(room_id, bot)
        except Exception:
            pass


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
            InlineKeyboardButton(text="🔴 أحمر", callback_data=f"cl_{room_id}_🔴"),
            InlineKeyboardButton(text="🔵 أزرق", callback_data=f"cl_{room_id}_🔵")
        ],
        [
            InlineKeyboardButton(text="🟡 أصفر", callback_data=f"cl_{room_id}_🟡"),
            InlineKeyboardButton(text="🟢 أخضر", callback_data=f"cl_{room_id}_🟢")
        ]
    ]
    hand_txt = "، ".join(hand) if hand else "—"
    await c.message.edit_text(
        f"🎨 اختر اللون الجديد:\n\n🃏 أوراقك: {hand_txt}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=color_kb)
    )
    db_query("UPDATE rooms SET discard_pile = %s WHERE room_id = %s",
        (json.dumps(discard_pile), room_id), commit=True)
    pending_color_data[room_id] = {
        'card_played': card,
        'p_idx': p_idx,
        'prev_color': room['current_color']
    }
    cd_msg = await _send_message_then_delete(c.bot, c.from_user.id, "⏳ باقي 20 ثانية لاختيار اللون\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢", delete_after_seconds=5)
    if cd_msg:
        if c.from_user.id not in temp_messages:
            temp_messages[c.from_user.id] = []
        temp_messages[c.from_user.id].append(cd_msg.message_id)
        color_timers[room_id] = asyncio.create_task(color_timeout_2p(room_id, c.bot, c.from_user.id))

async def start_new_round(room_id, bot, start_turn_idx=0, alert_msgs=None):
    try:
        room_res = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_res:
            return
        players = get_ordered_players(room_id)

        for p in players:
            if p['user_id'] in player_ui_msgs:
                player_ui_msgs[p['user_id']] = {}

        deck = generate_h2o_deck()

        for p in players:
            hand = [deck.pop(0) for _ in range(7)]
            db_query("UPDATE room_players SET hand = %s, said_uno = FALSE, last_msg_id = NULL, is_ready = FALSE WHERE user_id = %s", (json.dumps(hand), p['user_id']), commit=True)

        while any(x in deck[0] for x in ["🌈", "🔥", "💧", "🌊"]):
            random.shuffle(deck)
        top_card = deck.pop(0)
        current_color = top_card.split()[0]

        db_query("UPDATE rooms SET deck = %s, top_card = %s, current_color = %s, turn_index = %s, discard_pile = '[]', status = 'playing' WHERE room_id = %s",
            (json.dumps(deck), top_card, current_color, start_turn_idx, room_id), commit=True)

        for p in players:
            if p['user_id'] == BOT_USER_ID:
                continue
            try:
                await bot.send_message(p['user_id'], "🎮 بدأت اللعبة! استعد...")
            except:
                pass

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
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة", show_alert=True)
        room = room_data[0]
        players = get_ordered_players(room_id)
        p_idx = room['turn_index']
        if players[p_idx]['user_id'] != c.from_user.id:
            return await c.answer("❌ مو دورك! انتظر الخصم يلعب.", show_alert=True)

        await asyncio.sleep(0)

        hand = sort_hand(safe_load(players[p_idx]['hand']))
        if idx >= len(hand):
            return await c.answer("⚠️ حدث خطأ في اختيار الورقة", show_alert=True)

        card = hand[idx]
        p_name = players[p_idx].get('player_name') or "لاعب"
        opp_idx = (p_idx + 1) % 2
        opp_id = players[opp_idx]['user_id']

        if not check_validity(card, room['top_card'], room['current_color']):
            deck = ensure_deck_from_discard(room_id, room)
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

        # جوكر +4 مسموح فقط إذا ما عندك أي ورقة تشتغل (لون أو رقم مطابق)
        if "🔥" in card:
            other_valid = [c for c in hand if c != card and "🔥" not in c and check_validity(c, room['top_card'], room['current_color'])]
            if other_valid:
                try:
                    from i18n import t
                    msg = t(c.from_user.id, "wild4_only_when_no_valid")
                except Exception:
                    msg = "⛔ جوكر +4 تقدر تلعبها فقط إذا ما عندك ورقة تشتغل! عندك ورقة مناسبة."
                await c.answer(msg, show_alert=True)
                return await refresh_ui_2p(room_id, c.bot)

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
            row = db_query("SELECT online_points FROM users WHERE user_id = %s", (c.from_user.id,))
            cur_online = (row[0]['online_points'] or 0) if row else 0
            db_query("UPDATE users SET online_points = %s WHERE user_id = %s",
                (cur_online + points, c.from_user.id), commit=True)
            db_query("UPDATE rooms SET discard_pile = %s, top_card = %s, current_color = %s WHERE room_id = %s",
                (json.dumps(discard_pile), card, card.split()[0], room_id), commit=True)
            db_query("DELETE FROM room_players WHERE room_id = %s", (room_id,), commit=True)
            is_training = bool(room.get("is_training"))
            win_text = f"🏆 **{p_name} فاز بالجولة!** 🏆\n📊 حصل على {points} نقطة."
            if is_training:
                try:
                    from i18n import t
                    win_text = t(c.from_user.id, "training_win_congrats") + "\n\n" + win_text
                except Exception:
                    pass
            from handlers.common import create_replay_session, build_game_end_keyboard
            winner_id = c.from_user.id
            opp_id = players[opp_idx]['user_id']
            is_ranked = bool(room.get('is_random'))
            try:
                from badges import badge_on_win, badge_on_loss
                if opp_id != BOT_USER_ID:
                    badge_on_loss(opp_id)
                badge_result = badge_on_win(winner_id, opp_id if opp_id != BOT_USER_ID else None, is_ranked)
                badge_just_earned = badge_result.get('new_badge_label') if badge_result.get('new_badge') else None
            except Exception as e:
                badge_result = {}
                badge_just_earned = None
            replay_id = create_replay_session(players, room, '2p', win_text, winner_id=winner_id, badge_just_earned=badge_just_earned)
            for p in players:
                if p['user_id'] == BOT_USER_ID:
                    continue
                end_kb = build_game_end_keyboard(replay_id, p['user_id'])
                await c.bot.send_message(p['user_id'], win_text, reply_markup=end_kb)
                if p['user_id'] == winner_id and badge_result:
                    if badge_result.get('reason'):
                        await c.bot.send_message(p['user_id'], "⚠️ " + badge_result['reason'])
                    elif badge_result.get('message'):
                        await c.bot.send_message(p['user_id'], badge_result['message'])
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
            db_query("UPDATE rooms SET top_card = %s, current_color = %s, discard_pile = %s, turn_index = %s WHERE room_id = %s",
                (card, new_color, json.dumps(discard_pile), next_turn, room_id), commit=True)
            alerts[c.from_user.id] = f"{symbol} منعت الخصم! الدور بقى إلك."
            alerts[opp_id] = f"{symbol} {p_name} منعك من اللعب!"
        elif "💧" in card:
            next_turn = await handle_draw1_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile)
        elif "🌊" in card:
            next_turn = await handle_draw2_card_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile)
        elif "+2" in card:
            next_turn = await handle_colored_draw2_action(c, room_id, p_idx, opp_id, opp_idx, card, room, players, alerts, discard_pile)

        db_query("UPDATE rooms SET turn_index = %s WHERE room_id = %s", (next_turn, room_id), commit=True)
        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
        current_id = c.from_user.id if next_turn == p_idx else opp_id
        check_p = db_query("SELECT hand FROM room_players WHERE user_id = %s", (current_id,))
        current_hand = safe_load(check_p[0]['hand']) if check_p else []
        can_play_now = False
        for c_check in current_hand:
            if check_validity(c_check, room['top_card'], room['current_color']):
                can_play_now = True
                break
        if not can_play_now:
            cancel_timer(room_id)
            cancel_auto_draw_task(room_id)
            if current_id == BOT_USER_ID:
                await refresh_ui_2p(room_id, c.bot, alerts)
                return
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

@router.callback_query(F.data.startswith("cl_"))
async def handle_color(c: types.CallbackQuery, state: FSMContext):
    try:
        parts = c.data.split("_")
        # الصيغة: cl_ROOMID_COLOR — اللون دائماً آخر جزء (إيموجي)
        if len(parts) >= 3:
            chosen_color = parts[-1]
            room_id = "_".join(parts[1:-1])
        elif len(parts) >= 2:
            data = await state.get_data()
            room_id = data.get('room_id')
            chosen_color = parts[1]
        else:
            room_id = None
            chosen_color = ""
        if not room_id or not chosen_color:
            return await c.answer("⚠️ انتهت صلاحية الاختيار. العب ورقة أخرى إن أمكن.", show_alert=True)
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
        await c.answer()
        state_data = await state.get_data()
        card = state_data.get('card_played') if room_id else None
        p_idx = state_data.get('p_idx')
        pending = pending_color_data.get(room_id) if room_id else None
        if card is None or p_idx is None:
            if pending:
                card = pending.get('card_played')
                p_idx = pending.get('p_idx')
        if card is None or p_idx is None:
            room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
            if not room_data:
                return await c.answer("⚠️ الغرفة غير موجودة.", show_alert=True)
            room = room_data[0]
            players = get_ordered_players(room_id)
            if not players or (c.from_user.id != players[0]['user_id'] and c.from_user.id != players[1]['user_id']):
                return await c.answer("⚠️ لست في هذه الغرفة.", show_alert=True)
            p_idx = 0 if players[0]['user_id'] == c.from_user.id else 1
            card = room.get('top_card') or '🌈 جوكر ألوان'

        task = color_timers.pop(room_id, None)
        if task and not task.done():
            task.cancel()
        await asyncio.sleep(0.1)

        cd = color_countdown_msgs.pop(room_id, None)
        if cd:
            try:
                await cd['bot'].delete_message(cd['chat_id'], cd['msg_id'])
            except:
                pass

        pending = pending_color_data.pop(room_id, None)
        prev_color = (pending or {}).get('prev_color')

        if room_id in color_timed_out:
            color_timed_out.discard(room_id)
            await state.clear()
            return

        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة.", show_alert=True)
        room = room_data[0]
        if prev_color is None:
            prev_color = room.get('current_color')
        players = get_ordered_players(room_id)
        opp_id = players[(p_idx + 1) % 2]['user_id']
        p_name = players[p_idx].get('player_name') or "لاعب"

        if "🔥" in card:
            if opp_id == BOT_USER_ID:
                deck = ensure_deck_from_discard(room_id, room)
                bot_hand = safe_load(players[(p_idx + 1) % 2]['hand'])
                for _ in range(4):
                    if not deck:
                        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                        deck = ensure_deck_from_discard(room_id, room)
                    if deck:
                        bot_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(bot_hand), BOT_USER_ID), commit=True)
                db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
                    (f"{card} {chosen_color}", chosen_color, p_idx, json.dumps(deck), room_id), commit=True)
                await state.clear()
                await _send_message_then_delete(c.bot, c.from_user.id, "🤖 البوت قبل السحب وسحب 4 ورقات. دورك!", delete_after_seconds=5)
                await refresh_ui_2p(room_id, c.bot)
                return
            kb = [[
                InlineKeyboardButton(text="🕵️‍♂️ أتحداك", callback_data=f"rs_y_{room_id}_{prev_color}_{chosen_color}"),
                InlineKeyboardButton(text="✅ قبول", callback_data=f"rs_n_{room_id}_{chosen_color}")
            ]]
            await c.bot.send_message(
                opp_id,
                f"🚨 {p_name} لعب 🔥 +4 وغير اللون لـ {chosen_color}!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
            cd_msg = await _send_message_then_delete(c.bot, opp_id, "⏳ باقي 20 ثانية للرد\n🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢", delete_after_seconds=5)
            if cd_msg:
                challenge_countdown_msgs[room_id] = {'bot': c.bot, 'chat_id': opp_id, 'msg_id': cd_msg.message_id}
                challenge_timers[room_id] = asyncio.create_task(challenge_timeout_2p(room_id, c.bot))
            await c.message.edit_text("⏳ بانتظار الخصم...")
            await state.clear()
            return

        penalty = 1 if "💧" in card else (2 if "🌊" in card else 0)
        deck = ensure_deck_from_discard(room_id, room)
        alerts = {}

        if penalty > 0:
            opp_h = safe_load(players[(p_idx + 1) % 2]['hand'])
            for _ in range(penalty):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                (json.dumps(opp_h), opp_id), commit=True)
            next_turn = p_idx
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} وسحبك {penalty} ورقة والدور رجع له!"
            alerts[c.from_user.id] = f"🎨 اخترت اللون {chosen_color} وسحب الخصم {penalty} ورقة!"
        else:
            # جوكر ألوان (🌈): الدور يرجع للاعب نفسه (2 لاعب)
            next_turn = p_idx
            alerts[opp_id] = f"🎨 {p_name} اختار اللون {chosen_color} — دورك لاحقاً."
            alerts[c.from_user.id] = f"🎨 اخترت اللون {chosen_color} والدور بقى إلك!"

        db_query("UPDATE rooms SET top_card = %s, current_color = %s, turn_index = %s, deck = %s WHERE room_id = %s",
            (f"{card} {chosen_color}", chosen_color, next_turn, json.dumps(deck), room_id), commit=True)

        await state.clear()
        await refresh_ui_2p(room_id, c.bot, alerts)

    except Exception as e:
        print(f"Color Error: {e}")
        try:
            await c.answer("⚠️ حدث خطأ في اختيار اللون.", show_alert=True)
        except Exception:
            pass


@router.callback_query(F.data.startswith("challenge_"))
async def handle_challenge_decision(c: types.CallbackQuery):
    try:
        data = c.data.split("_")
        decision = data[1]
        room_id = data[2]
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)

        if room_id in challenge_timers:
            challenge_timers[room_id].cancel()
            del challenge_timers[room_id]
        if room_id in challenge_countdown_msgs:
            cd_info = challenge_countdown_msgs.pop(room_id)
            try:
                await c.bot.delete_message(cd_info['chat_id'], cd_info['msg_id'])
            except:
                pass

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

        deck = ensure_deck_from_discard(room_id, room)
        if decision == "n":
            opp_hand = safe_load(players[opp_idx]['hand'])
            for _ in range(4):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    opp_hand.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
            db_query("UPDATE rooms SET deck = %s, turn_index = %s, current_color = 'ANY' WHERE room_id = %s", (json.dumps(deck), p_idx, room_id), commit=True)
            if opp_id != BOT_USER_ID:
                await _send_message_then_delete(c.bot, opp_id, "✅ قبلت السحب! سحبت 4 ورقات.", delete_after_seconds=5)
            if user_id != BOT_USER_ID:
                await _send_message_then_delete(c.bot, user_id, "✅ خصمك قبل السحب! دورك الآن ويمكنك لعب أي لون.", delete_after_seconds=5)
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
                    if not deck:
                        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                        deck = ensure_deck_from_discard(room_id, room)
                    if deck:
                        p_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(p_hand), user_id), commit=True)
                db_query("UPDATE rooms SET deck = %s, turn_index = %s WHERE room_id = %s", (json.dumps(deck), opp_idx, room_id), commit=True)
                if user_id != BOT_USER_ID:
                    await _send_message_then_delete(c.bot, user_id, "🕵️‍♂️ كشف الغش! سحبت 6 أوراق عقوبة والخصم يأخذ الدور!", delete_after_seconds=5)
                if opp_id != BOT_USER_ID:
                    await _send_message_then_delete(c.bot, opp_id, "✅ نجح التحدي! الخصم كان لديه ورقة مناسبة غير الجوكر.", delete_after_seconds=5)
            else:
                opp_hand = safe_load(players[opp_idx]['hand'])
                for _ in range(6):
                    if not deck:
                        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                        deck = ensure_deck_from_discard(room_id, room)
                    if deck:
                        opp_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s", (json.dumps(opp_hand), opp_id), commit=True)
                db_query("UPDATE rooms SET deck = %s, turn_index = %s, current_color = 'ANY' WHERE room_id = %s", (json.dumps(deck), p_idx, room_id), commit=True)
                if opp_id != BOT_USER_ID:
                    await _send_message_then_delete(c.bot, opp_id, "❌ فشل التحدي! أنت تسحب 6 أوراق.", delete_after_seconds=5)
                if user_id != BOT_USER_ID:
                    await _send_message_then_delete(c.bot, user_id, "🎯 الخصم فشل في التحدي – العب بأي لون.", delete_after_seconds=5)

        try:
            await c.message.delete()
        except:
            pass
        await refresh_ui_2p(room_id, c.bot)
    except Exception as e:
        print(f"[handle_challenge_decision] Error: {e}")
        await c.answer("⚠️ خطأ أثناء معالجة قرار التحدي.", show_alert=True)


@router.callback_query(F.data.startswith("un_"))
async def handle_uno(c: types.CallbackQuery):
    try:
        room_id = c.data.split("_")[1]
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
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
        except:
            pass
        await refresh_ui_2p(room_id, c.bot, alerts)
    except Exception as e:
        print(f"Uno Error: {e}")


@router.callback_query(F.data.startswith("ct_"))
async def handle_catch(c: types.CallbackQuery):
    try:
        room_id = c.data.split("_")[1]
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
        players = get_ordered_players(room_id)
        opp = next(p for p in players if p['user_id'] != c.from_user.id)
        opp_h = safe_load(opp['hand'])
        me = next((p for p in players if p['user_id'] == c.from_user.id), None)
        p_name = me.get('player_name') if me else "لاعب"
        opp_name = opp.get('player_name') or "لاعب"
        if len(opp_h) == 1 and not str(opp.get('said_uno')).lower() in ['true', '1']:
            room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
            deck = ensure_deck_from_discard(room_id, room_data)
            for _ in range(2):
                if not deck:
                    room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room_data)
                if deck:
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s, said_uno = FALSE WHERE user_id = %s", (json.dumps(opp_h), opp['user_id']), commit=True)
            db_query("UPDATE rooms SET deck = %s WHERE room_id = %s", (json.dumps(deck), room_id), commit=True)
            await c.answer()
            try:
                if IMG_CATCH_SUCCESS and IMG_CATCH_SUCCESS != "123":
                    await _send_photo_then_schedule_delete(c.bot, c.from_user.id, IMG_CATCH_SUCCESS)
                if IMG_CATCH_PENALTY and IMG_CATCH_PENALTY != "123":
                    await _send_photo_then_schedule_delete(c.bot, opp['user_id'], IMG_CATCH_PENALTY)
            except:
                pass
            alerts = {
                c.from_user.id: f"🪤 صدت {opp_name}! سحب ورقتين لأنه نسي الاونو.",
                opp['user_id']: f"⚠️ {p_name} صادك! سحبت ورقتين لأنك نسيت تصيح اونو!"
            }
            await refresh_ui_2p(room_id, c.bot, alerts)
        else:
            await c.answer("❌ ما تگدر تصيده حالياً!")
    except Exception as e:
        print(f"Catch Error: {e}")


@router.callback_query(F.data.startswith("ex_"))
async def ask_exit(c: types.CallbackQuery):
    rid = c.data.split("_")[1]
    cancel_auto_draw_task(rid)
    cancel_timer(rid)
    kb = [[InlineKeyboardButton(text="✅ نعم", callback_data=f"cf_ex_{rid}"), InlineKeyboardButton(text="❌ لا", callback_data=f"cn_ex_{rid}")]]
    await c.message.edit_text("🚪 هل أنت متأكد من الانسحاب؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith("cf_ex_"))
async def confirm_exit(c: types.CallbackQuery):
    rid = c.data.split("_")[2]
    cancel_auto_draw_task(rid)
    cancel_timer(rid)
    try:
        await c.message.delete()
    except:
        pass
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
    cancel_auto_draw_task(rid)
    cancel_timer(rid)
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
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة")
        room = room_data[0]
        players = get_ordered_players(room_id)
        curr_idx = room['turn_index']
        if c.from_user.id != players[curr_idx]['user_id']:
            return await c.answer("❌ مو دورك تمرر!", show_alert=True)

        # وضع التدريب: لا يوجد مرر دور — الزر غير معروض؛ إن ضُغط من رسالة قديمة نرفض
        if room.get("is_training"):
            await c.answer("📚 في التدريب ما يوجد مرر دور — انتظر السحب التلقائي (5 ثواني).", show_alert=True)
            return

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
        decision = parts[1]
        room_id = parts[2]
        cancel_auto_draw_task(room_id)
        cancel_timer(room_id)
        cancel_challenge_timer(room_id)


        room_data = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))
        if not room_data:
            return await c.answer("⚠️ الغرفة غير موجودة", show_alert=True)
        room = room_data[0]

        players = get_ordered_players(room_id)
        p_idx = room['turn_index']
        opp_idx = (p_idx + 1) % 2
        deck = ensure_deck_from_discard(room_id, room)
        alerts = {}

        if decision == "n":
            opp_h = safe_load(players[opp_idx]['hand'])
            for _ in range(4):
                if not deck:
                    room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                    deck = ensure_deck_from_discard(room_id, room)
                if deck:
                    opp_h.append(deck.pop(0))
            db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                (json.dumps(opp_h), players[opp_idx]['user_id']), commit=True)
            next_turn = p_idx
            final_col = parts[3]
            alerts[players[p_idx]['user_id']] = "✅ الخصم قبل السحب والدور رجع الك!"
            alerts[players[opp_idx]['user_id']] = "📥 قبلت السحب وسحبت 4 ورقات وعبر دورك."
        else:
            prev_col = parts[3]
            chosen_col = parts[4]
            p_hand = safe_load(players[p_idx]['hand'])
            cheated = False
            for card in p_hand:
                if any(x in card for x in ["🌈", "🔥", "💧", "🌊"]):
                    continue
                if check_validity(card, room['top_card'], prev_col):
                    cheated = True
                    break
            if cheated:
                for _ in range(6):
                    if not deck:
                        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                        deck = ensure_deck_from_discard(room_id, room)
                    if deck:
                        p_hand.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                    (json.dumps(p_hand), players[p_idx]['user_id']), commit=True)
                next_turn = opp_idx
                alerts[players[p_idx]['user_id']] = "🕵️‍♂️ كشفك الخصم! سحبت 6 ورقات عقوبة."
                alerts[players[opp_idx]['user_id']] = "✅ نجح التحدي! الخصم كان يغش وسحب 6 ورقات."
                final_col = chosen_col
            else:
                opp_h = safe_load(players[opp_idx]['hand'])
                for _ in range(6):
                    if not deck:
                        room = db_query("SELECT * FROM rooms WHERE room_id = %s", (room_id,))[0]
                        deck = ensure_deck_from_discard(room_id, room)
                    if deck:
                        opp_h.append(deck.pop(0))
                db_query("UPDATE room_players SET hand = %s WHERE user_id = %s",
                    (json.dumps(opp_h), players[opp_idx]['user_id']), commit=True)
                next_turn = p_idx
                alerts[players[p_idx]['user_id']] = "❌ فشل تحدي الخصم وسحب 6 ورقات! الدور الك."
                alerts[players[opp_idx]['user_id']] = "❌ فشل التحدي! سحبت 6 ورقات."
                final_col = chosen_col

        db_query("""
            UPDATE rooms
            SET deck = %s, turn_index = %s, current_color = %s, top_card = %s
            WHERE room_id = %s
        """, (json.dumps(deck), next_turn, final_col, f"🔥 جوكر+4 {final_col}", room_id), commit=True)
        try:
            await c.message.delete()
        except:
            pass
        await refresh_ui_2p(room_id, c.bot, alerts)
    except Exception as e:
        print(f"Challenge Error (rs_): {e}")
        await c.answer("⚠️ حدث خطأ أثناء معالجة التحدي", show_alert=True)

