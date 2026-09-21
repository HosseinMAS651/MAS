(()=>{
'use strict';
document.querySelectorAll('.delete-room-form').forEach(form=>form.addEventListener('submit',event=>{
  if(!window.confirm('این اتاق و فایل‌های وابسته حذف شوند؟'))event.preventDefault();
}));
})();
