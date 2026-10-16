import React, { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Modal } from './Modal';

interface QrModalProps {
  isOpen: boolean;
  onClose: () => void;
  roomName: string;
  publicToken: string | null;
}

export const QrModal: React.FC<QrModalProps> = ({ isOpen, onClose, roomName, publicToken }) => {
  const [qrDataUrl, setQrDataUrl] = useState<string>('');
  const [copied, setCopied] = useState<boolean>(false);

  const publicUrl = publicToken
    ? `${window.location.origin}/public/${publicToken}`
    : '';

  useEffect(() => {
    if (publicUrl) {
      QRCode.toDataURL(publicUrl, {
        width: 280,
        margin: 2,
        color: {
          dark: '#1e3a8a',
          light: '#ffffff',
        },
      })
        .then((url) => setQrDataUrl(url))
        .catch(() => {});
    }
  }, [publicUrl]);

  const handleCopy = () => {
    if (!publicUrl) return;
    navigator.clipboard.writeText(publicUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="لینک تماشاگران و کیوآرکد (QR Code)">
      <div className="space-y-5 text-center">
        <p className="text-sm text-gray-600 dark:text-slate-300">
          تماشاگران می‌توانند با اسکن این کیوآرکد یا باز کردن لینک زیر، بدون نیاز به ثبت‌نام و ورود،
          روند سخنرانی، زمان‌بندی و فایل‌های زندهٔ اتاق «{roomName}» را به صورت لحظه‌ای مشاهده کنند.
        </p>

        {qrDataUrl && (
          <div className="flex flex-col items-center justify-center p-4 bg-gray-50 dark:bg-slate-800 rounded-2xl border border-gray-100 dark:border-slate-700">
            <img src={qrDataUrl} alt="QR Code" className="w-56 h-56 rounded-xl shadow-md bg-white p-2" />
            <a
              href={qrDataUrl}
              download={`qr-${roomName}.png`}
              className="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 font-medium"
            >
              ⬇ دریافت تصویر کیوآرکد (PNG)
            </a>
          </div>
        )}

        <div className="space-y-2">
          <label className="text-xs font-bold text-gray-500 dark:text-slate-400 block text-right">آدرس مستقیم تماشاگر:</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={publicUrl}
              dir="ltr"
              className="flex-1 px-3 py-2 text-xs bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-xl font-mono text-gray-700 dark:text-slate-200 select-all"
            />
            <button
              onClick={handleCopy}
              className={`px-4 py-2 rounded-xl text-xs font-bold transition-colors ${
                copied
                  ? 'bg-emerald-600 text-white'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {copied ? 'کپی شد!' : 'کپی لینک'}
            </button>
          </div>
        </div>

        <div className="pt-2">
          <a
            href={publicUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-block text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 font-bold"
          >
            مشاهده صفحه تماشاگر در برگه جدید ↗
          </a>
        </div>
      </div>
    </Modal>
  );
};
