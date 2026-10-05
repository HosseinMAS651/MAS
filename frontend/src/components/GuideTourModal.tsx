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
    title: 'شروع کار با مـاس',
    icon: '🎙️',
    description: 'مـاس برای مدیریت ترتیب سخنرانان، زمان هر نوبت، فایل‌های رویداد و پخش عمومی ساخته شده است. کنترل تایمر همیشه در اختیار مالک اتاق می‌ماند.',
    tips: [
      'از صفحهٔ اتاق‌ها، اتاقی بسازید و نام، ظرفیت و زمان‌بندی همگانی یا فردی را تنظیم کنید.',
      'از جزئیات اتاق، QR یا پیوند عمومی را برای مخاطبان بفرستید؛ تماشاگر برای دیدن صفحه به حساب کاربری نیاز ندارد.',
      'فایل‌های صوتی ذخیره‌شده را در آرشیو با دکمهٔ پخش مستقیماً در مرورگر گوش کنید؛ دانلود نیز جداگانه در دسترس است.',
    ],
  },
  {
    title: 'حالت سخنران و کد ورود',
    icon: '🔑',
    description: 'حالت سخنران را از تنظیمات اتاق روشن کنید. در صفحهٔ عمومی، هر فرد نقش تماشاگر یا سخنران را انتخاب می‌کند؛ سخنران با کد اختصاصی جایگاهش وارد می‌شود.',
    tips: [
      'مالک در جزئیات اتاق کد چهارکاراکتری هر سخنران را می‌بیند و می‌تواند همان کد را بچرخاند.',
      'خاموش و روشن‌کردن حالت، کد را عوض نمی‌کند؛ چرخاندن کد، دسترسی قبلی را باطل می‌کند.',
      'هر کد در هر لحظه فقط روی یک دستگاه فعال است؛ ورود از دستگاه تازه، نشست دستگاه قبلی را جایگزین می‌کند.',
      'سخنران پس از ورود باید میکروفون همان دستگاه را صریحاً فعال کند تا وضعیتش «آماده» شود.',
    ],
  },
  {
    title: 'تایمر و ضبط از دستگاه سخنران',
    icon: '⏱️',
    description: 'مالک نوبت‌ها و تایمر را کنترل می‌کند. وقتی نوبت سخنران در حال اجرا باشد، حالت سخنران صدای میکروفون دستگاهی را ضبط می‌کند که با آن به صفحهٔ عمومی وارد شده است.',
    tips: [
      'پیش از شروع رویداد، سخنران باید با پیوند عمومی وارد شود، کد را ثبت کند و اجازهٔ میکروفون بدهد.',
      'تا وقتی مالک تایمر را برای آن سخنران فعال نکرده، ضبط خودکار شروع نمی‌شود؛ توقف تایمر ضبط را نیز متوقف می‌کند.',
      'برای ضبط از دستگاه سخنران، روشن‌بودن حالت سخنران کافی است و گزینهٔ ضبط معمولی اتاق مرجع این حالت نیست.',
      'هشدار نوبت می‌تواند صدا، لرزش یا اعلان مرورگر داشته باشد؛ به مجوز و پشتیبانی دستگاه وابسته است و با بسته‌بودن صفحه تضمین نمی‌شود.',
    ],
  },
  {
    title: 'فایل‌ها و صفحهٔ تماشاگران',
    icon: '📱',
    description: 'مالک می‌تواند فایل‌های رویداد را مدیریت کند و تعیین کند چه چیزی برای مخاطبان عمومی نمایش داده شود.',
    tips: [
      'برای دریافت فایل از سخنران، اجازهٔ ارسال فایل را روشن کنید؛ هر فایل تازه ابتدا در صف خصوصی تأیید مالک قرار می‌گیرد.',
      'فایل سخنران تا تأیید مالک برای تماشاگران منتشر نمی‌شود. تنظیم نمایش زندهٔ فایل‌ها نیز باید اجازهٔ نمایش عمومی بدهد.',
      'تماشاگر می‌تواند فایل صوتی را درون صفحه پخش کند و فایل‌های دیگر را، بسته به نوعشان، پیش‌نمایش یا باز کند.',
      'لینک عمومی را فقط با افراد موردنظر به اشتراک بگذارید؛ چرخاندن توکن عمومی، پیوند قبلی را باطل می‌کند.',
    ],
  },
  {
    title: 'امنیت حساب و بازیابی رمز',
    icon: '🛡️',
    description: 'کد بازیابی یک‌بارمصرف تنها راه خودخدمت برای بازنشانی رمز در نسخهٔ فعلی است؛ آن را جدا از رمز عبور نگه دارید.',
    tips: [
      'کد هنگام ثبت‌نام یک بار نمایش داده می‌شود؛ سامانه متن آن را ذخیره نمی‌کند و بعداً دوباره نشان نمی‌دهد.',
      'پس از ورود، از پروفایل با رمز فعلی کد تازه بسازید؛ کد تازه بلافاصله کد پیشین را باطل می‌کند.',
      'اگر رمز و کد را هر دو از دست دادید، مدیر سرور باید رمز را با ابزار امن `scripts/reset_password.py` بازنشانی کند.',
      'برای پیام‌های پس‌زمینه، مجوز اعلان را از صفحهٔ سخنران بدهید و محدودیت‌های مرورگر/سیستم‌عامل را در نظر بگیرید.',
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
    <Modal isOpen={isOpen} onClose={onClose} title="راهنمای جامع کاربری سامانه مـاس" maxWidth="max-w-2xl">
      <div className="space-y-6 text-right">
        <div className="flex items-center gap-3 border-b border-gray-100 dark:border-slate-800 pb-4">
          <span className="text-3xl p-3 bg-blue-50 dark:bg-blue-950/60 rounded-2xl">{step.icon}</span>
          <div>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">{step.title}</h3>
            <span className="text-xs text-blue-600 dark:text-blue-400 font-bold">
              بخش {currentStep + 1} از {GUIDE_STEPS.length}
            </span>
          </div>
        </div>

        <p className="text-sm text-gray-600 dark:text-slate-300 leading-relaxed">{step.description}</p>

        <div className="bg-gray-50 dark:bg-slate-900/80 rounded-2xl p-4 border border-gray-100 dark:border-slate-800 space-y-2.5">
          <span className="text-xs font-bold text-gray-500 dark:text-slate-400 block mb-1">راهنمای گام‌به‌گام:</span>
          {step.tips.map((tip, idx) => (
            <div key={idx} className="flex items-start gap-2 text-xs text-gray-700 dark:text-slate-200 leading-6">
              <span className="text-blue-600 dark:text-blue-400 font-black mt-0.5">✓</span>
              <span>{tip}</span>
            </div>
          ))}
        </div>

        <div className="flex justify-center gap-1.5 pt-2" aria-label="انتخاب بخش راهنما">
          {GUIDE_STEPS.map((guideStep, idx) => (
            <button
              key={guideStep.title}
              type="button"
              onClick={() => setCurrentStep(idx)}
              aria-label={`بخش ${idx + 1}: ${guideStep.title}`}
              aria-current={idx === currentStep ? 'step' : undefined}
              className={`h-2 rounded-full transition-all ${
                idx === currentStep ? 'w-8 bg-blue-600' : 'w-2 bg-gray-200 dark:bg-slate-700'
              }`}
            />
          ))}
        </div>

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
