(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("recordings-data")?.textContent || "{}");
  document.querySelectorAll(".delete-file").forEach(button => {
    button.addEventListener("click", async () => {
      if (!confirm("این فایل ضبط‌شده حذف شود؟")) return;
      button.disabled = true;
      try {
        const fd = new FormData();
        fd.append("csrf", data.csrf || "");
        const response = await fetch(`/files/${button.dataset.fileId}/delete`, {method: "POST", body: fd, credentials: "same-origin"});
        if (!response.ok) throw new Error("delete failed");
        location.reload();
      } catch (_) {
        button.disabled = false;
        alert("حذف فایل ناموفق بود.");
      }
    });
  });
})();
