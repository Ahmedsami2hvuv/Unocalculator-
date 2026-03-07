import asyncio
import os
import logging

# تحميل .env إن وُجد (مثلاً عند التشغيل المحلي أو على بعض السيرفرات)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import bot
from database import init_db
# استدعاء الراوترات مباشرة من الملفات
from handlers.admin import router as admin_router
from handlers.common import router as common_router, _get_admin_ids
from handlers.reports import router as reports_router
from handlers.room_2p import router as room_2p_router
from handlers.room_multi import router as room_multi_router
from handlers.calc import router as calc_router
from handlers.stats import router as stats_router

# روتر النشر أولاً حتى تُعالَج رسائل «نشر منشور» من مجتمع الأونو قبل أي معالج آخر
try:
    from handlers.community_publish import router as community_publish_router
    _use_publish_router = True
except Exception as e:
    community_publish_router = None
    _use_publish_router = False
    print(f"⚠️ تعذّر تحميل community_publish — زر «مجتمع الأونو» لن يعمل: {e}")

logging.basicConfig(level=logging.INFO)

async def main():
    # 1. تهيئة قاعدة البيانات أولاً
    init_db()

    # 2. إعداد الموزع (Dispatcher) مع ذاكرة مؤقتة للـ States
    dp = Dispatcher(storage=MemoryStorage())

    # 3. ربط الراوترات: common أولاً حتى يصل طلب المساعدة (حالة help_request) للإدارة قبل أي معالج آخر
    dp.include_router(common_router)
    if _use_publish_router:
        dp.include_router(community_publish_router)
    dp.include_router(admin_router)
    dp.include_router(reports_router)
    dp.include_router(room_2p_router)
    dp.include_router(room_multi_router)
    dp.include_router(calc_router)
    dp.include_router(stats_router)

    print("🚀 البوت انطلق بنجاح والبيانات آمنة!")
    admin_ids = _get_admin_ids()
    help_chat = (os.getenv("HELP_CHAT_ID") or "").strip().strip('"').strip("'")
    logging.info("ADMIN_ID(s)=%s  HELP_CHAT_ID=%s — إن كانت فارغة فلن تصل طلبات المساعدة والتبليغات للمدير.", list(admin_ids), help_chat or "(غير مضبوط)")
    if not admin_ids and not help_chat:
        print("\n" + "=" * 60)
        print("⚠️  تحذير: رسائل «طلب المساعدة» والتبليغات لن تصل للإدارة!")
        print("   لوصول الرسائل للمدير، ضع في متغيرات البيئة (أو في ملف .env):")
        print("   • ADMIN_ID=رقم_تليجرام_للمدير  (مثال: 123456789)")
        print("   • أو HELP_CHAT_ID=معرف_المجموعة (مثال: -1001234567890)")
        print("   وتأكد أن المدير ضغط /start على البوت مرة واحدة على الأقل.")
        print("=" * 60 + "\n")

    # 4. تنظيف التحديثات المعلقة
    await bot.delete_webhook(drop_pending_updates=True)

    # 5. بدء الاستماع للرسائل
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("❌ تم إيقاف البوت!")
