import asyncio
import logging
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import bot
from database import init_db
# استدعاء الراوترات مباشرة من الملفات
from handlers.admin import router as admin_router
from handlers.common import router as common_router
from handlers.room_2p import router as room_2p_router
from handlers.room_multi import router as room_multi_router
from handlers.calc import router as calc_router
from handlers.stats import router as stats_router

# روتر النشر أولاً حتى تُعالَج رسائل «نشر منشور» من مجتمع الأونو قبل أي معالج آخر
try:
    from handlers.community_publish import router as community_publish_router
    _use_publish_router = True
except Exception:
    community_publish_router = None
    _use_publish_router = False

logging.basicConfig(level=logging.INFO)

async def main():
    # 1. تهيئة قاعدة البيانات أولاً
    init_db()

    # 2. إعداد الموزع (Dispatcher) مع ذاكرة مؤقتة للـ States
    dp = Dispatcher(storage=MemoryStorage())

    # 3. ربط الراوترات بالترتيب الصحيح (النشر أولاً ثم الأدمن ثم الباقي)
    if _use_publish_router:
        dp.include_router(community_publish_router)
    dp.include_router(admin_router)
    dp.include_router(common_router)
    dp.include_router(room_2p_router)
    dp.include_router(room_multi_router)
    dp.include_router(calc_router)
    dp.include_router(stats_router)

    print("🚀 البوت انطلق بنجاح والبيانات آمنة!")

    # 4. تنظيف التحديثات المعلقة
    await bot.delete_webhook(drop_pending_updates=True)

    # 5. بدء الاستماع للرسائل
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("❌ تم إيقاف البوت!")
