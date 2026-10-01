import React, { useState } from 'react';
import { Modal } from './Modal';

interface GuideStep {
  title: string;
  icon: string;
  description: string;
  tips: string[];
}

const GUIDE_STEPS: GuideStep[] = [
  {
    title: 'خوش‌آمدید به مـاس (مدیریت زمان سخنرانی)',
    icon: '🎙️',
    description: 'سامانه‌ای حرفه‌ای، فوق‌سریع و پایدار برای مدیریت رویدادها، همایش‌ها و ارائه‌های چندسخنرانه.',
    tips: [
      'قابلیت تعریف اتاق با ظرفیت‌های مختلف و زمان‌بندی همگانی یا فردی.',
      'کنترل روان تایمر، ثبت خودکار اضافه‌وقت، و ضبط صدا برای هر سخنران.',
      'لینک تماشاگران عمومی بدون نیاز به لاگین همراه با نمایش آنلاین اسلایدها و واکنش‌های زنده.',
    ],
  },
  {
    title: 'تنظیمات سخنرانان و ترتیب ارائه',
    icon: '👥',
    description: 'شما کنترل کاملی بر روی چینش، اولویت‌بندی و زمان‌بندی هر سخنران دارید.',
    tips: [
      'ترتیب دستی: جابه‌جایی سریع و بصری با دکمه‌های بالا/پایین در جدول سخنرانان.',
      'ترتیب الفبایی: مرتب‌سازی هوشمند خودکار بر اساس حروف الفبا.',
      'ترتیب سنی: اولویت‌بندی احترام‌آمیز از سن بالاتر به پایین‌تر.',
      'امکان خروج از فریز (Unfreeze) و بازنشانی کلیه سخنرانان با یک کلیک.',
    ],
  },
  {
    title: 'اتاق پخش زنده و کنترل تایمر',
    icon: '⏱️',
    description: 'داشبورد بلادرنگ مجری با پاسخ‌دهی آنی و دقت میلی‌ثانیه‌ای.',
    tips: [
      'کلیدهای میانبر و دکمه‌های پرسرعت برای شروع، توقف، ثبت پایان و پرش به سخنران دیگر.',
      'هشدار صوتی و لرزشی دقیق هنگام پایان وقت سخنرانی.',
      'تغییر وضعیت دریافت واکنش‌های تماشاگران (Floating Reactions) در هر لحظه.',
      'دانلود گزارش رسمی PDF کامل رویداد با فرمت استاندارد و سازمانی.',
    ],
  },
  {
    title: 'صفحه تماشاگران و فایل‌های زنده',
    icon: '📱',
    description: 'تجربه تعاملی و لذت‌بخش برای مخاطبان همایش بدون نصب هیچ اپلیکیشن اضافی.',
    tips: [
      'امکان مشاهده اسلایدها و فایل‌های پیوست به‌صورت درون‌صفحه‌ای (Inline Live Viewer).',
      'فایل‌های اختصاصی هر فرد فقط در نوبت سخنرانی خودش به نمایش درمی‌آیند.',
      'ارسال واکنش‌های زنده (ایموجی‌های شناور به سبک اینستاگرام لایو).',
      'پشتیبانی کامل از حالت تاریک (Dark Mode) و روشن برای راحتی چشم مخاطبان.',
    ],
  },
];

interface GuideTourModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const GuideTourModal: React.FC<GuideTourModalProps> = ({ isOpen, onClose }) => {
  const [currentStep, setCurrentStep] = useState(0);

  if (!isOpen) return null;

  const step = GUIDE_STEPS[currentStep];

  const handleNext = () => {
    if (currentStep < GUIDE_STEPS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      onClose();
      setCurrentStep(0);
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="راهنمای جامع کاربری سامانه مـاس" maxWidth="max-w-xl">
      <div className="space-y-6 text-right">
        {/* هدر مرحله */}
        <div className="flex items-center gap-3 border-b border-gray-100 dark:border-slate-800 pb-4">
          <span className="text-3xl p-3 bg-blue-50 dark:bg-blue-950/60 rounded-2xl">{step.icon}</span>
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">{step.title}</h3>
            <span className="text-xs text-blue-600 dark:text-blue-400 font-bold">
              بخش {currentStep + 1} از {GUIDE_STEPS.length}
            </span>
          </div>
        </div>

        {/* توضیحات مرحله */}
        <p className="text-sm text-gray-600 dark:text-slate-300 leading-relaxed">{step.description}</p>

        {/* نکات کلیدی */}
        <div className="bg-gray-50 dark:bg-slate-900/80 rounded-2xl p-4 border border-gray-100 dark:border-slate-800 space-y-2.5">
          <span className="text-xs font-bold text-gray-500 dark:text-slate-400 block mb-1">ویژگی‌های برجسته:</span>
          {step.tips.map((tip, idx) => (
            <div key={idx} className="flex items-start gap-2 text-xs text-gray-700 dark:text-slate-200">
              <span className="text-blue-600 dark:text-blue-400 font-black mt-0.5">✓</span>
              <span>{tip}</span>
            </div>
          ))}
        </div>

        {/* نقاط پیشرفت */}
        <div className="flex justify-center gap-1.5 pt-2">
          {GUIDE_STEPS.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentStep(idx)}
              className={`h-2 rounded-full transition-all ${
                idx === currentStep ? 'w-8 bg-blue-600' : 'w-2 bg-gray-200 dark:bg-slate-700'
              }`}
            />
          ))}
        </div>

        {/* دکمه‌های هدایت */}
        <div className="flex items-center justify-between pt-4 border-t border-gray-100 dark:border-slate-800">
          <button
            type="button"
            onClick={handlePrev}
            disabled={currentStep === 0}
            className={`px-4 py-2 text-xs font-bold rounded-xl transition-all ${
              currentStep === 0
                ? 'opacity-30 cursor-not-allowed text-gray-400'
                : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800'
            }`}
          >
            ← مرحله قبلی
          </button>

          <button
            type="button"
            onClick={handleNext}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold text-xs rounded-xl shadow-md shadow-blue-600/20 transition-all"
          >
            {currentStep === GUIDE_STEPS.length - 1 ? 'متوجه شدم و بستن' : 'مرحله بعدی →'}
          </button>
        </div>
      </div>
    </Modal>
  );
};
