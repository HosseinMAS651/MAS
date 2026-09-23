import React from 'react';
import { Modal } from './Modal';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({ isOpen, onClose, onConfirm, title, message, confirmText='تأیید', cancelText='انصراف', danger=true }) => {
  const [loading, setLoading] = React.useState(false);
  const handleConfirm = async () => {
    if (loading) return;
    setLoading(true);
    try { await onConfirm(); onClose(); } finally { setLoading(false); }
  };
  return (
    <Modal isOpen={isOpen} onClose={loading ? () => {} : onClose} title={title} maxWidth="max-w-md">
      <div className="space-y-4">
        <p className="text-sm text-gray-600 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-3 pt-3">
          <button disabled={loading} onClick={onClose} className="px-4 py-2 border border-gray-300 rounded-xl text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50">{cancelText}</button>
          <button disabled={loading} onClick={handleConfirm} className={`px-5 py-2 rounded-xl text-sm font-bold text-white transition-colors disabled:opacity-50 ${danger ? 'bg-red-600 hover:bg-red-700 shadow-lg shadow-red-600/20' : 'bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-600/20'}`}>
            {loading ? 'در حال انجام…' : confirmText}
          </button>
        </div>
      </div>
    </Modal>
  );
};
