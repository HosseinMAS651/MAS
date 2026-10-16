import React from 'react';
import { Modal } from './Modal';

interface OvertimeModalProps {
  isOpen: boolean;
  speakerName: string;
  onContinue: () => void;
  onFinish: () => void;
  isRecording: boolean;
}

export const OvertimeModal: React.FC<OvertimeModalProps> = ({
  isOpen,
  speakerName,
  onContinue,
  onFinish,
  isRecording,
}) => {
  return (
    <Modal isOpen={isOpen} onClose={() => {}} title="اعلان اتمام زمان سخنرانی" maxWidth="max-w-md">
      <div className="text-center space-y-4">
        <div className="w-16 h-16 bg-amber-100 text-amber-600 rounded-full flex items-center justify-center mx-auto text-2xl font-bold animate-pulse">
          ⏱
        </div>
        <div>
          <h4 className="text-xl font-bold text-gray-900">
            زمان مجاز {speakerName ? `«${speakerName}»` : 'سخنران جاری'} به پایان رسید!
          </h4>
          <p className="text-sm text-gray-500 mt-2">
            تایمر متوقف شد. {isRecording && 'ضبط صدا نیز موقتاً متوقف شده است.'}
            برای ادامه سخنرانی دکمهٔ «ادامه سخنرانی» را بزنید تا زمان اضافه محاسبه شود، یا «اتمام سخنرانی» را انتخاب کنید تا سخنرانی پایان یافته و فایل ضبط ذخیره شود.
          </p>
        </div>

        <div className="pt-4 flex flex-col sm:flex-row gap-3 justify-center">
          <button
            onClick={onContinue}
            className="flex-1 px-5 py-3 bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl shadow-lg shadow-amber-600/20 transition-all hover:-translate-y-0.5"
          >
            ادامه سخنرانی (+ زمان اضافه)
          </button>
          <button
            onClick={onFinish}
            className="flex-1 px-5 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-600/20 transition-all hover:-translate-y-0.5"
          >
            اتمام سخنرانی {isRecording && 'و ذخیره ضبط'}
          </button>
        </div>
      </div>
    </Modal>
  );
};
